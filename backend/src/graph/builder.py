"""Build the GraphRAG knowledge graph from a list of articles.

Pipeline per article:
  article -> chunk_article() -> for each chunk: extract entities + relations
          -> embed entity name+description (batched via 火山引擎)
          -> upsert entities, upsert relations, link MENTIONED_IN

Idempotency:
  - MERGE on entity_id so re-runs accumulate mention_count
  - Caller can pass `skip_hashes` to skip already-processed articles
  - MERGE on relation (source, target, type) so duplicates collapse

Failure handling:
  - Per-chunk errors are logged and skipped (other chunks still process)
  - Embedding failures fail the whole batch (caller can decide to retry)
  - Neo4j write failures raise GraphStoreError (caller decides whether to
    continue without the graph layer)
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from core import GraphStoreError, get_logger, settings
from vectorstore.embedding import embed_texts_async

from ingestion.chunker import chunk_article

from . import normalizer
from .extractor import EntityRelationExtractor
from .neo4j_store import Neo4jStore
from .schema import DocumentNode, Entity, Relation

logger = get_logger(__name__)


# Idempotency ledger: a JSON file with content_hashes of articles we've
# already processed. Lives in data/ (gitignored, safe to delete to rebuild).
_LEDGER_PATH = settings.data_dir / "graph_processed.json"


def _load_ledger() -> set[str]:
    if not _LEDGER_PATH.exists():
        return set()
    try:
        return set(json.loads(_LEDGER_PATH.read_text()))
    except Exception:
        return set()


def _save_ledger(processed: set[str]) -> None:
    _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER_PATH.write_text(json.dumps(sorted(processed), indent=2))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def build_graph_for_articles(
    articles: list[dict[str, Any]],
    store: Neo4jStore | None = None,
    extractor: EntityRelationExtractor | None = None,
    *,
    skip_existing: bool = True,
    save_ledger: bool = True,
) -> dict[str, int]:
    """Build (or extend) the knowledge graph from a batch of articles.

    Args:
        articles: list of article dicts (same shape as indexer accepts).
        store: optional Neo4jStore (creates one if not provided).
        extractor: optional EntityRelationExtractor (creates one if not provided).
        skip_existing: if True, skip articles whose content_hash was already processed.
        save_ledger: if True, persist the idempotency ledger after success.

    Returns:
        stats dict with keys: articles_in, articles_skipped, chunks_processed,
        entities_upserted, relations_upserted, errors.
    """
    stats = {
        "articles_in": len(articles),
        "articles_skipped": 0,
        "chunks_processed": 0,
        "entities_upserted": 0,
        "relations_upserted": 0,
        "errors": 0,
    }
    if not articles:
        return stats

    if not settings.graph_enabled:
        logger.info("graph_build_skipped_disabled")
        return stats

    processed = _load_ledger() if skip_existing else set()
    to_process = []
    for a in articles:
        h = a.get("content_hash")
        if h and h in processed:
            stats["articles_skipped"] += 1
            continue
        to_process.append(a)

    if not to_process:
        logger.info("graph_build_all_skipped", skipped=stats["articles_skipped"])
        return stats

    own_store = store is None
    own_extractor = extractor is None
    store = store or Neo4jStore()
    extractor = extractor or EntityRelationExtractor()

    try:
        if own_store:
            await store._get_driver()  # eagerly init so we fail fast on bad creds
            await store.init_indexes()

        # 1. Chunk all articles (sync, fast)
        all_chunks: list[dict[str, Any]] = []
        chunk_to_doc: dict[str, dict[str, Any]] = {}  # chunk_id -> article dict
        for article in to_process:
            chunks = chunk_article(
                {
                    "title": article.get("title", ""),
                    "pub_time": article.get("pub_time", ""),
                    "source": article.get("source", ""),
                    "lead": article.get("lead", ""),
                    "content": article.get("content", ""),
                },
                max_chars=3500,
            )
            parent_doc_id = article.get("content_hash") or article.get("external_id", "")
            for i, ch in enumerate(chunks):
                ch_id = f"{parent_doc_id}:{i}"
                ch["chunk_id"] = ch_id
                ch["parent_doc_id"] = parent_doc_id
                all_chunks.append(ch)
                chunk_to_doc[ch_id] = article

        if not all_chunks:
            return stats

        stats["chunks_processed"] = len(all_chunks)
        logger.info("graph_build_extraction_start", chunks=len(all_chunks))

        # 2. Extract entities + relations from all chunks (parallel, bounded)
        results = await extractor.extract_for_chunks(all_chunks)

        # 3. Aggregate, stamp source_chunk_id, build Documents
        all_entities: list[Entity] = []
        all_relations: list[Relation] = []
        docs_to_upsert: dict[str, DocumentNode] = {}

        for chunk, (entities, relations) in zip(all_chunks, results):
            chunk_id = chunk["chunk_id"]
            for e in entities:
                e.source_chunk_ids = [chunk_id]
            for r in relations:
                r.source_chunk_ids = [chunk_id]
            all_entities.extend(entities)
            all_relations.extend(relations)

            article = chunk_to_doc[chunk_id]
            parent_doc_id = chunk["parent_doc_id"]
            if parent_doc_id and parent_doc_id not in docs_to_upsert:
                docs_to_upsert[parent_doc_id] = DocumentNode(
                    doc_id=parent_doc_id,
                    title=article.get("title", ""),
                    source=article.get("source", ""),
                    published_at=int(article.get("published_at") or 0),
                    url=article.get("url", ""),
                    language=article.get("language", ""),
                )

        if not all_entities and not all_relations:
            logger.info("graph_build_no_extraction_results", chunks=len(all_chunks))
            return stats

        # 4. Dedupe entities (same entity_id) — merge source_chunk_ids, descriptions
        unique_entities = _dedupe_entities(all_entities)
        logger.info(
            "graph_build_extraction_done",
            chunks=len(all_chunks),
            raw_entities=len(all_entities),
            unique_entities=len(unique_entities),
            raw_relations=len(all_relations),
        )

        # 5. Embed entity name + description (batched)
        texts_to_embed = [f"{e.name}: {e.description}" for e in unique_entities]
        try:
            embeddings = await embed_texts_async(
                texts_to_embed, batch_size=settings.graph_extraction_batch_size * 4
            )
        except Exception as e:
            stats["errors"] += 1
            logger.error("graph_build_embedding_failed", error=str(e))
            raise

        for e, emb in zip(unique_entities, embeddings):
            e.embedding = emb

        # 6. Upsert documents first (so chunks can link)
        if docs_to_upsert:
            for doc in docs_to_upsert.values():
                await store.upsert_document(doc)

        # 7. Upsert entities
        stats["entities_upserted"] = await store.upsert_entities(unique_entities)

        # 8. Upsert relations
        stats["relations_upserted"] = await store.upsert_relations(all_relations)

        # 9. Link entities to their source chunks
        #    (Chunk nodes are virtual — we don't store their full content in the
        #    graph, just an ID and the MENTIONED_IN relationship.)
        link_tasks = []
        for chunk, (entities, _) in zip(all_chunks, results):
            for e in entities:
                # Re-resolve entity_id from the unique_entities (the source chunks
                # were stamped on the raw entities, but dedup may have collapsed them)
                eid = normalizer.make_entity_id(e.name, e.type)
                link_tasks.append(store.link_entity_to_chunk(eid, chunk["chunk_id"]))
        if link_tasks:
            await asyncio.gather(*link_tasks, return_exceptions=True)

        # 10. Persist ledger
        if save_ledger and skip_existing:
            for a in to_process:
                h = a.get("content_hash")
                if h:
                    processed.add(h)
            _save_ledger(processed)

        logger.info("graph_build_complete", **stats)
        return stats

    finally:
        if own_extractor:
            await extractor.close()
        if own_store:
            await store.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dedupe_entities(entities: list[Entity]) -> list[Entity]:
    """Collapse entities with the same entity_id; merge source_chunk_ids.

    We pick the entity with the longest description as the canonical
    representative. `mention_count` becomes the number of times the entity
    was extracted (which the UPSERT then converts into Neo4j's
    mention_count += 1 on each MATCH).
    """
    by_id: dict[str, Entity] = {}
    for e in entities:
        existing = by_id.get(e.entity_id)
        if existing is None:
            by_id[e.entity_id] = Entity(
                entity_id=e.entity_id,
                name=e.name,
                type=e.type,
                description=e.description,
                embedding=None,  # filled in after embedding
                mention_count=1,
                source_chunk_ids=list(e.source_chunk_ids),
            )
        else:
            existing.mention_count += 1
            for cid in e.source_chunk_ids:
                if cid not in existing.source_chunk_ids:
                    existing.source_chunk_ids.append(cid)
            if len(e.description) > len(existing.description):
                existing.description = e.description
    return list(by_id.values())


__all__ = ["build_graph_for_articles", "_LEDGER_PATH"]
