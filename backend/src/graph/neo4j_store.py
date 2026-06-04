"""Thin async wrapper around the Neo4j Python driver.

Why a wrapper:
  - Centralizes connection lifecycle (lazy init, single driver per process).
  - Hides Cypher template strings from callers (they live in schema.py).
  - Adds a small retry layer for transient Bolt errors.
  - Surfaces our GraphStoreError (CRITICAL) instead of leaking driver errors.

Why not the official `neo4j-graphrag` package:
  - We don't need its retriever/templates — we have our own LightRAG-style
    flow (extractor + builder + retriever) that doesn't map onto their
    Pipeline/Retriever abstractions.
  - Pulling in neo4j-graphrag would drag in langchain-core and PyPDF — too
    much weight for a 4-core server.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import tenacity
from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError

from core import GraphStoreError, get_logger, settings

from . import schema as graph_schema

logger = get_logger(__name__)


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (ServiceUnavailable, SessionExpired, TransientError))


_retry = tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    retry=tenacity.retry_if_exception(_is_transient),
    reraise=True,
)


class Neo4jStore:
    """Async Neo4j client tailored for our graph schema.

    Usage:
        store = Neo4jStore()
        await store.init_indexes()
        await store.upsert_entities([entity1, entity2])
        await store.close()
    """

    def __init__(self, uri: str | None = None, user: str | None = None,
                 password: str | None = None, database: str | None = None):
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self._database = database or settings.neo4j_database
        self._driver: AsyncDriver | None = None

    async def _get_driver(self) -> AsyncDriver:
        if self._driver is None:
            if not self._password:
                raise GraphStoreError(
                    "NEO4J_PASSWORD is not set. Set it in configs/.env.dev "
                    "or via the NEO4J_PASSWORD environment variable."
                )
            self._driver = AsyncGraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                max_connection_pool_size=20,
                connection_timeout=10.0,
            )
            logger.info("neo4j_driver_initialized", uri=self._uri, database=self._database)
        return self._driver

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
            logger.info("neo4j_driver_closed")

    async def __aenter__(self) -> Neo4jStore:
        await self._get_driver()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    @_retry
    async def init_indexes(self) -> None:
        """Create the vector + fulltext indexes used by retrieval (idempotent)."""
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            await session.execute_write(_init_indexes_tx, graph_schema.EMBEDDING_DIM)
            logger.info("neo4j_indexes_ready")

    async def health_check(self) -> bool:
        try:
            driver = await self._get_driver()
            async with driver.session(database=self._database) as session:
                result = await session.run("RETURN 1 AS ok")
                record = await result.single()
                return bool(record and record.get("ok") == 1)
        except Exception as e:
            logger.warning("neo4j_health_check_failed", error=str(e))
            return False

    # ------------------------------------------------------------------
    # Write APIs (used by builder)
    # ------------------------------------------------------------------

    @_retry
    async def upsert_entities(self, entities: list[graph_schema.Entity]) -> int:
        if not entities:
            return 0
        driver = await self._get_driver()
        params = [
            {
                "entity_id": e.entity_id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "embedding": e.embedding,
            }
            for e in entities
        ]
        async with driver.session(database=self._database) as session:
            count = await session.execute_write(_upsert_entities_tx, params)
        return count

    @_retry
    async def upsert_relations(self, relations: list[graph_schema.Relation]) -> int:
        if not relations:
            return 0
        # Group by (source, target, type) and merge keywords client-side.
        merged = _merge_relations(relations)
        params = [
            {
                "source_id": _resolve_entity_id(r.source, "Concept"),
                "target_id": _resolve_entity_id(r.target, "Concept"),
                "type": r.type,
                "description": r.description,
                "keywords": r.keywords,
                "weight": r.weight,
                "source_chunk_ids": r.source_chunk_ids,
            }
            for r in merged
        ]
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            count = await session.execute_write(_upsert_relations_tx, params)
        return count

    @_retry
    async def link_entity_to_chunk(
        self,
        entity_id: str,
        chunk_id: str,
    ) -> None:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            await session.execute_write(
                _link_entity_chunk_tx, {"entity_id": entity_id, "chunk_id": chunk_id}
            )

    @_retry
    async def link_chunk_to_doc(self, chunk_id: str, doc_id: str) -> None:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            await session.execute_write(
                _link_chunk_doc_tx, {"chunk_id": chunk_id, "doc_id": doc_id}
            )

    @_retry
    async def upsert_document(self, doc: graph_schema.DocumentNode) -> None:
        driver = await self._get_driver()
        params = {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "source": doc.source,
            "published_at": doc.published_at,
            "url": doc.url,
            "language": doc.language,
        }
        async with driver.session(database=self._database) as session:
            await session.execute_write(_upsert_document_tx, params)

    # ------------------------------------------------------------------
    # Read APIs (used by GraphRetriever in Phase 3)
    # ------------------------------------------------------------------

    @_retry
    async def vector_search_entities(
        self, embedding: list[float], top_k: int = 10
    ) -> list[dict[str, Any]]:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.execute_read(
                _vector_search_entities_tx,
                {"embedding": embedding, "top_k": top_k},
            )
        return result

    @_retry
    async def entity_neighbors_chunks(self, entity_id: str) -> list[dict[str, Any]]:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.execute_read(
                _entity_neighbors_chunks_tx, {"entity_id": entity_id}
            )
        return result

    @_retry
    async def fulltext_search_relations(
        self, query: str, top_k: int = 20
    ) -> list[dict[str, Any]]:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            result = await session.execute_read(
                _fulltext_search_relations_tx, {"query": query, "top_k": top_k}
            )
        return result

    @_retry
    async def stats(self) -> dict[str, int]:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            rows = await session.execute_read(_stats_tx, {})
        return {row["label"]: row["count"] for row in rows if row.get("label")}

    # ------------------------------------------------------------------
    # Phase 5: introspection queries for the graph viz API
    # ------------------------------------------------------------------

    @_retry
    async def entity_subgraph(
        self, name: str, entity_id: str | None = None
    ) -> dict[str, Any] | None:
        """Return the 1-hop neighborhood of an entity.

        ``name`` is the public-facing canonical name (e.g. "苹果"). The
        optional ``entity_id`` lets callers disambiguate when two entity
        types share a name (the index is ``name`` so we accept either).
        """
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            rows = await session.execute_read(
                _entity_subgraph_tx,
                {"name": name, "entity_id": entity_id or name},
            )
        return rows[0] if rows else None

    @_retry
    async def chunk_graph(self, chunk_id: str) -> list[dict[str, Any]]:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            rows = await session.execute_read(
                _chunk_graph_tx, {"chunk_id": chunk_id}
            )
        return rows

    @_retry
    async def top_entities(self, limit: int = 20) -> list[dict[str, Any]]:
        driver = await self._get_driver()
        async with driver.session(database=self._database) as session:
            rows = await session.execute_read(
                _top_entities_tx, {"limit": limit}
            )
        return rows


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_entity_id(name: str, fallback_type: str) -> str:
    """Build the entity_id from a canonical name. Type is unknown at this
    point (LLM extracted relations may not have type in the relation payload);
    we use a placeholder that the upsert query doesn't care about because
    we MATCH on entity_id directly."""
    from .normalizer import normalize_entity_name
    return f"{normalize_entity_name(name)}:{fallback_type}"


def _merge_relations(relations: Iterable[graph_schema.Relation]) -> list[graph_schema.Relation]:
    """Combine relations that share (source, target, type) into one row with
    merged keywords/weight=MAX/chunk_ids deduped."""
    by_key: dict[tuple[str, str, str], graph_schema.Relation] = {}
    for r in relations:
        key = (r.source, r.target, r.type)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = graph_schema.Relation(
                source=r.source,
                target=r.target,
                type=r.type,
                description=r.description,
                keywords=list(r.keywords),
                weight=r.weight,
                source_chunk_ids=list(r.source_chunk_ids),
            )
        else:
            for kw in r.keywords:
                if kw not in existing.keywords:
                    existing.keywords.append(kw)
            for cid in r.source_chunk_ids:
                if cid not in existing.source_chunk_ids:
                    existing.source_chunk_ids.append(cid)
            existing.weight = max(existing.weight, r.weight)
            # Keep the longest description (most informative)
            if len(r.description) > len(existing.description):
                existing.description = r.description
    return list(by_key.values())


# Transaction functions (sync functions called by execute_write/execute_read)
def _init_indexes_tx(tx: Any, dim: int) -> None:
    tx.run(graph_schema.CREATE_VECTOR_INDEX_ENTITY, dim=dim)
    tx.run(graph_schema.CREATE_FULLTEXT_INDEX_ENTITY)
    tx.run(graph_schema.CREATE_FULLTEXT_INDEX_RELATION)
    tx.run(graph_schema.CREATE_INDEX_ENTITY_NAME)


def _upsert_entities_tx(tx: Any, params: list[dict]) -> int:
    result = tx.run(
        "UNWIND $batch AS row " + graph_schema.UPSERT_ENTITY,
        batch=params,
    )
    return result.consume().counters.nodes_created


def _upsert_relations_tx(tx: Any, params: list[dict]) -> int:
    result = tx.run(
        "UNWIND $batch AS row " + graph_schema.UPSERT_RELATION,
        batch=params,
    )
    return result.consume().counters.relationships_created


def _link_entity_chunk_tx(tx: Any, params: dict) -> None:
    tx.run(graph_schema.LINK_ENTITY_TO_CHUNK, **params)


def _link_chunk_doc_tx(tx: Any, params: dict) -> None:
    tx.run(graph_schema.LINK_CHUNK_TO_DOC, **params)


def _upsert_document_tx(tx: Any, params: dict) -> None:
    tx.run(
        """
        MERGE (d:Document {doc_id: $doc_id})
        ON CREATE SET d.title = $title, d.source = $source,
                      d.published_at = $published_at, d.url = $url, d.language = $language
        ON MATCH SET d.title = $title, d.source = $source,
                      d.published_at = $published_at, d.url = $url, d.language = $language
        """,
        **params,
    )


def _vector_search_entities_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.VECTOR_SEARCH_ENTITIES, **params)
    return [dict(record) for record in result]


def _entity_neighbors_chunks_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.ENTITY_NEIGHBORS_AND_CHUNKS, **params)
    return [dict(record) for record in result]


def _fulltext_search_relations_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.FULLTEXT_SEARCH_RELATIONS, **params)
    return [dict(record) for record in result]


def _stats_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.GRAPH_STATS, **params)
    return [dict(record) for record in result]


def _entity_subgraph_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.ENTITY_SUBGRAPH, **params)
    return [dict(record) for record in result]


def _chunk_graph_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.CHUNK_GRAPH, **params)
    return [dict(record) for record in result]


def _top_entities_tx(tx: Any, params: dict) -> list[dict]:
    result = tx.run(graph_schema.TOP_ENTITIES, **params)
    return [dict(record) for record in result]
