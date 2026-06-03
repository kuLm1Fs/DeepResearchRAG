"""LLM-based entity and relation extraction for GraphRAG.

Two-step extraction (per plan):
  1. extract_entities — get all entities (name, type, description) from chunk
  2. extract_relations — get all relations between those entities

We separate them because:
  - Smaller, more focused output schema per call → higher reliability
  - One failure doesn't lose both entities AND relations
  - Easier to add a third call later (e.g. event detection) without breaking the rest
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import tenacity
from openai import APIStatusError, APITimeoutError, APIConnectionError

from core import GraphExtractionError, get_logger, settings
from llm.client import BaseLLM, create_llm

from . import normalizer
from .schema import (
    EMBEDDING_DIM,
    Entity,
    EntityType,
    Relation,
)

logger = get_logger(__name__)

_RETRYABLE = (APITimeoutError, APIConnectionError, APIStatusError)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in {429, 500, 502, 503}:
        return True
    return False


_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    retry=tenacity.retry_if_exception(_is_retryable),
    before_sleep=lambda rs: logger.warning(
        "extraction_retry",
        attempt=rs.attempt_number,
        error=str(rs.outcome.exception()) if rs.outcome else "",
    ),
    reraise=True,
)


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def _parse_json_object(text: str) -> dict[str, Any]:
    """Find the first {...} JSON object in `text` and return it.
    Mirrors the helper in agent/nodes.py but kept local to avoid coupling."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(stripped):
        if ch != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise GraphExtractionError(f"No JSON object found in LLM response: {text[:200]}...")


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class EntityRelationExtractor:
    """Extract entities and relations from chunks using an LLM.

    The LLM is expected to support JSON-mode (`response_format={"type": "json_object"}`).
    Both DeepSeek and OpenAI (and Qwen via compatible mode) support this.
    """

    def __init__(
        self,
        llm: BaseLLM | None = None,
        max_entities_per_chunk: int | None = None,
        max_relations_per_chunk: int | None = None,
        min_description_length: int | None = None,
    ):
        self.llm = llm or create_llm(
            provider=settings.llm_provider,
            api_key=_api_key_for(settings.llm_provider),
            model=settings.llm_model,
        )
        self.max_entities = max_entities_per_chunk or settings.graph_max_entities_per_chunk
        self.max_relations = max_relations_per_chunk or settings.graph_max_relations_per_chunk
        self.min_desc_len = (
            min_description_length or settings.graph_entity_min_description_length
        )

    async def close(self) -> None:
        if self.llm is not None:
            await self.llm.close()

    @_retry
    async def _llm_json(self, prompt: str) -> dict[str, Any]:
        """Single LLM call with JSON mode enabled."""
        from agent.templates import load_prompt  # lazy to avoid import cycle
        # The prompt is already built; we just call LLM with json_object mode.
        messages = [{"role": "user", "content": prompt}]
        # DeepSeek/OpenAI/Qwen all support response_format={"type":"json_object"}
        # but DeepSeek may also need the `json_object` value; fall back to plain
        # text if the provider rejects it.
        try:
            response = await self.llm.chat(
                messages, response_format={"type": "json_object"}
            )
        except TypeError:
            # Some providers don't accept response_format; retry without it.
            response = await self.llm.chat(messages)
        return _parse_json_object(response)

    async def extract_entities(self, chunk_text: str) -> list[Entity]:
        """Step 1: extract entities from a chunk."""
        from agent.templates import load_prompt

        prompt = load_prompt("extract_entities", version="v2", chunk=chunk_text[:3500])
        try:
            data = await self._llm_json(prompt)
        except Exception as e:
            logger.warning("extract_entities_failed", error=str(e))
            return []

        raw_list = data.get("entities") or []
        if not isinstance(raw_list, list):
            return []

        entities: list[Entity] = []
        for raw in raw_list[: self.max_entities]:
            if not isinstance(raw, dict):
                continue
            ent = normalizer.normalize_entity(
                raw,
                source_chunk_id="",  # set by caller
                min_description_length=self.min_desc_len,
            )
            if ent is not None:
                entities.append(ent)
        return entities

    async def extract_relations(
        self, chunk_text: str, entities: list[Entity]
    ) -> list[Relation]:
        """Step 2: extract relations, conditioned on the entity list."""
        from agent.templates import load_prompt

        if not entities:
            return []

        entity_table = "\n".join(
            f"- {e.name} ({e.type})" for e in entities
        )
        prompt = load_prompt(
            "extract_relations",
            version="v2",
            chunk=chunk_text[:3500],
            entities=entity_table,
        )
        try:
            data = await self._llm_json(prompt)
        except Exception as e:
            logger.warning("extract_relations_failed", error=str(e))
            return []

        raw_list = data.get("relations") or []
        if not isinstance(raw_list, list):
            return []

        relations: list[Relation] = []
        for raw in raw_list[: self.max_relations]:
            if not isinstance(raw, dict):
                continue
            rel = normalizer.normalize_relation(
                raw,
                source_chunk_id="",  # set by caller
                min_description_length=self.min_desc_len,
            )
            if rel is not None:
                relations.append(rel)
        return relations

    async def extract_for_chunk(
        self, chunk_id: str, chunk_text: str
    ) -> tuple[list[Entity], list[Relation]]:
        """Two-step extraction for one chunk. Returns (entities, relations)."""
        entities = await self.extract_entities(chunk_text)
        if not entities:
            return [], []
        relations = await self.extract_relations(chunk_text, entities)
        # Stamp source_chunk_id now that we have it
        for e in entities:
            e.source_chunk_ids = [chunk_id]
        for r in relations:
            r.source_chunk_ids = [chunk_id]
        return entities, relations

    async def extract_for_chunks(
        self, chunks: list[dict[str, Any]]
    ) -> list[tuple[list[Entity], list[Relation]]]:
        """Process a list of chunks in parallel (bounded by asyncio.gather).

        Each chunk dict must have at least `chunk_id` and `content`.
        """
        sem = asyncio.Semaphore(settings.graph_extraction_batch_size)

        async def _one(chunk: dict[str, Any]) -> tuple[list[Entity], list[Relation]]:
            async with sem:
                try:
                    return await self.extract_for_chunk(
                        chunk["chunk_id"], chunk["content"]
                    )
                except Exception as e:
                    logger.warning(
                        "extract_chunk_failed",
                        chunk_id=chunk.get("chunk_id"),
                        error=str(e),
                    )
                    return [], []

        results = await asyncio.gather(*[_one(c) for c in chunks])
        return list(results)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_key_for(provider: str) -> str:
    """Pick the right API key for the configured provider."""
    if provider == "deepseek":
        return settings.deepseek_api_key
    if provider == "openai":
        return settings.openai_api_key
    if provider == "qwen":
        return settings.qwen_api_key
    return settings.deepseek_api_key


# Re-export for convenience
__all__ = [
    "EntityRelationExtractor",
    "EMBEDDING_DIM",
    "EntityType",
    "Entity",
    "Relation",
]
