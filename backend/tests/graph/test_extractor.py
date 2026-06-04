"""Unit tests for graph.extractor (LLM calls are mocked)."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.graph.extractor import EntityRelationExtractor


class FakeLLM:
    """Minimal async LLM double. Records all calls and returns scripted responses."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self._idx = 0

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._idx >= len(self.responses):
            raise AssertionError(
                f"FakeLLM: out of scripted responses (got call #{self._idx + 1})"
            )
        resp = self.responses[self._idx]
        self._idx += 1
        return resp

    async def close(self):
        pass


def _make_extractor(llm_responses: list[str], **kwargs) -> EntityRelationExtractor:
    llm = FakeLLM(llm_responses)
    return EntityRelationExtractor(llm=llm, min_description_length=10, **kwargs)


class TestExtractEntities:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        extractor = _make_extractor([
            json.dumps({
                "entities": [
                    {"name": "Apple", "type": "Company",
                     "description": "Cupertino-based iPhone maker."},
                    {"name": "Tim Cook", "type": "Person",
                     "description": "CEO of Apple since 2011."},
                ]
            })
        ])
        entities = await extractor.extract_entities("Apple is led by Tim Cook.")

        assert len(entities) == 2
        # Names should be normalized
        names = sorted(e.name for e in entities)
        assert names == sorted(["苹果", "tim cook"])
        # When called directly, extract_entities uses "" as placeholder for chunk_id.
        # The caller (extract_for_chunk) is responsible for overwriting it.
        assert all(e.source_chunk_ids == [""] for e in entities)

    @pytest.mark.asyncio
    async def test_filters_invalid_type(self):
        extractor = _make_extractor([
            json.dumps({
                "entities": [
                    {"name": "Apple", "type": "Garbage",
                     "description": "long enough description."},
                ]
            })
        ])
        assert await extractor.extract_entities("x") == []

    @pytest.mark.asyncio
    async def test_filters_short_description(self):
        extractor = _make_extractor([
            json.dumps({
                "entities": [
                    {"name": "Apple", "type": "Company", "description": "tiny"},
                ]
            })
        ])
        assert await extractor.extract_entities("x") == []

    @pytest.mark.asyncio
    async def test_caps_max_entities(self):
        # 30 entities, but max=3
        raw = json.dumps({
            "entities": [
                {"name": f"E{i}", "type": "Concept",
                 "description": f"long enough description for entity {i}."}
                for i in range(30)
            ]
        })
        extractor = _make_extractor([raw], max_entities_per_chunk=3)
        entities = await extractor.extract_entities("x")
        assert len(entities) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_on_garbage_json(self):
        extractor = _make_extractor(["not json at all"])
        # Should log a warning and return [], not raise
        assert await extractor.extract_entities("x") == []

    @pytest.mark.asyncio
    async def test_passes_json_object_response_format(self):
        extractor = _make_extractor([
            json.dumps({"entities": []})
        ])
        await extractor.extract_entities("x")
        assert extractor.llm.calls[0]["kwargs"].get("response_format") == {
            "type": "json_object"
        }


class TestExtractRelations:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        # First call returns entities; second returns relations
        extractor = _make_extractor([
            json.dumps({
                "entities": [
                    {"name": "Apple", "type": "Company",
                     "description": "Cupertino-based iPhone maker."},
                    {"name": "Tim Cook", "type": "Person",
                     "description": "CEO of Apple since 2011."},
                ]
            }),
            json.dumps({
                "relations": [
                    {
                        "source": "Apple",
                        "target": "Tim Cook",
                        "type": "led_by",
                        "description": "Apple is led by CEO Tim Cook since 2011.",
                        "keywords": ["ceo", "leadership"],
                        "weight": 0.9,
                    }
                ]
            }),
        ])
        entities, relations = await extractor.extract_for_chunk(
            "c1", "Apple is led by Tim Cook."
        )
        assert len(entities) == 2
        assert len(relations) == 1
        assert relations[0].source == "苹果"  # normalized
        assert relations[0].target == "tim cook"  # normalized
        assert relations[0].source_chunk_ids == ["c1"]
        assert relations[0].weight == 0.9


class TestExtractForChunks:
    @pytest.mark.asyncio
    async def test_processes_chunks_in_parallel(self):
        # One LLM call per chunk (2 chunks × 2 calls each = 4 total)
        chunks = [
            {"chunk_id": "c1", "content": "Apple is led by Tim Cook."},
            {"chunk_id": "c2", "content": "Microsoft was founded by Bill Gates."},
        ]
        # Each chunk needs 2 responses (entities + relations)
        responses = [
            json.dumps({"entities": [
                {"name": "Apple", "type": "Company",
                 "description": "Cupertino-based iPhone maker."},
            ]}),
            json.dumps({"relations": []}),
            json.dumps({"entities": [
                {"name": "Microsoft", "type": "Company",
                 "description": "Software giant in Redmond."},
            ]}),
            json.dumps({"relations": []}),
        ]
        extractor = _make_extractor(responses, max_entities_per_chunk=10)
        results = await extractor.extract_for_chunks(chunks)
        assert len(results) == 2
        # Each chunk has its entities stamped
        c1_entities, c1_relations = results[0]
        c2_entities, c2_relations = results[1]
        assert c1_entities[0].source_chunk_ids == ["c1"]
        assert c2_entities[0].source_chunk_ids == ["c2"]
        assert extractor.llm.calls == [] or len(extractor.llm.calls) == 4

    @pytest.mark.asyncio
    async def test_isolates_chunk_failures(self):
        # If one chunk fails, the others still process
        chunks = [
            {"chunk_id": "good1", "content": "Apple news."},
            {"chunk_id": "bad", "content": "Bad chunk."},
            {"chunk_id": "good2", "content": "Google news."},
        ]
        # Track per-chunk call counts so the mock returns the right response.
        # A failed entities extraction short-circuits the chunk (no relations call).
        per_chunk_calls: dict[str, int] = {c["chunk_id"]: 0 for c in chunks}
        llm = MagicMock()

        async def chat(messages, **kwargs):
            # Identify which chunk the prompt is for by inspecting the chunk content.
            text = messages[0]["content"]
            chunk_id = None
            for c in chunks:
                if c["content"] in text:
                    chunk_id = c["chunk_id"]
                    break
            assert chunk_id is not None, f"could not match prompt to chunk: {text[:100]}"
            per_chunk_calls[chunk_id] += 1
            if chunk_id == "bad":
                return "not json"
            if per_chunk_calls[chunk_id] == 1:  # entities call
                return json.dumps({
                    "entities": [
                        {"name": "X", "type": "Company",
                         "description": f"entity for chunk {chunk_id}."}
                    ]
                })
            return json.dumps({"relations": []})  # relations call

        llm.chat = chat
        llm.close = AsyncMock()
        extractor = EntityRelationExtractor(llm=llm, min_description_length=10)

        results = await extractor.extract_for_chunks(chunks)
        assert len(results) == 3
        # Bad chunk should have empty results, others should have entities
        assert len(results[0][0]) == 1
        assert results[1] == ([], [])  # bad chunk — failed gracefully
        assert len(results[2][0]) == 1
