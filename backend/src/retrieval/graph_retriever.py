"""GraphRAG retrieval path: dual-level entity + relation search over Neo4j.

LightRAG-style: two parallel sub-paths that both end at chunks.

  Entity path   (low-level): embed query -> vector index on (Entity.embedding)
                              -> top-K entities -> 1-hop MENTIONED_IN + PART_OF
                              -> chunks
  Relation path (high-level): fulltext search on (RELATION.keywords, RELATION.description)
                              -> related entities' chunks via MENTIONED_IN + PART_OF

Results are merged by chunk_id; the chunk's final score is the average of
the entity-path score (vector distance) and the relation-path score
(fulltext score). Both are normalized to [0, 1] before averaging.

This class is intentionally decoupled from MultiPathRetriever: callers
plug it in as a 4th path and let the existing RRF fusion handle
ranking. The merge here is just for the graph path's internal dedup.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from core import GraphStoreError, get_logger
from vectorstore.embedding import embed_texts_async

if TYPE_CHECKING:
    # Only needed for the type annotation on __init__. Avoiding a
    # runtime import here side-steps a fragile case where pytest
    # collection loads ``src.graph.neo4j_store`` in one test module
    # and then a later module's eager ``from graph.neo4j_store
    # import Neo4jStore`` raises ModuleNotFoundError — Python's import
    # system has cached ``src.graph`` but not the bare ``graph`` key,
    # and prepending ``tests/graph`` to sys.path (pytest's default
    # behavior with __init__.py-bearing test dirs) shadows the package
    # lookup. See the same trick used for ``GraphRetriever`` import in
    # ``retriever.py``.
    from graph.neo4j_store import Neo4jStore

logger = get_logger(__name__)


class GraphRetriever:
    """Dual-level graph retriever (LightRAG-style).

    Usage:
        store = Neo4jStore()
        graph = GraphRetriever(store)
        chunks = await graph.retrieve("苹果公司最近投资了哪些公司？", top_k=10)
    """

    def __init__(
        self,
        store: Neo4jStore,
        entity_top_k: int = 10,
        relation_top_k: int = 20,
        max_neighbors_per_entity: int = 5,
    ):
        self.store = store
        self.entity_top_k = entity_top_k
        self.relation_top_k = relation_top_k
        self.max_neighbors_per_entity = max_neighbors_per_entity

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Run entity + relation paths in parallel, merge by chunk_id, return top-K.

        Returned chunk shape (matches the Milvus path where possible so
        RRF fusion can interleave them):
            chunk_id, content, title, url, source, language, category,
            published_at, score, via_entities: list[str],
            via_relations: list[dict], retrieval_path: "graph"

        Empty list if the graph layer is empty or both paths fail.
        """
        logger.info("graph_retrieval_started", query=query, top_k=top_k)
        try:
            query_embedding = (await embed_texts_async([query]))[0]
        except Exception as e:
            logger.warning("graph_retrieval_embed_failed", error=str(e))
            return []

        entity_chunks, relation_chunks = await asyncio.gather(
            self._entity_search(query, query_embedding),
            self._relation_search(query),
            return_exceptions=True,
        )

        # Tolerate partial failure: one path down is still useful.
        if isinstance(entity_chunks, BaseException):
            logger.warning("graph_entity_path_failed", error=str(entity_chunks))
            entity_chunks = []
        if isinstance(relation_chunks, BaseException):
            logger.warning("graph_relation_path_failed", error=str(relation_chunks))
            relation_chunks = []

        merged = self._merge(entity_chunks, relation_chunks)
        result = merged[:top_k]
        logger.info(
            "graph_retrieval_completed",
            entity_chunks=len(entity_chunks),
            relation_chunks=len(relation_chunks),
            returned=len(result),
        )
        return result

    # ------------------------------------------------------------------
    # Entity path
    # ------------------------------------------------------------------

    async def _entity_search(
        self, query: str, query_embedding: list[float]
    ) -> list[dict[str, Any]]:
        """Vector-search entities by embedding, then pull their chunk neighbors.

        Each entity contributes up to ``max_neighbors_per_entity`` chunks.
        Chunk score is the entity's vector score (Neo4j returns cosine
        similarity, already in [0, 1] for normalized vectors).
        """
        try:
            entities = await self.store.vector_search_entities(
                query_embedding, top_k=self.entity_top_k
            )
        except GraphStoreError as e:
            logger.warning("graph_vector_search_entities_failed", error=str(e))
            return []
        if not entities:
            return []

        # Fan out to chunk neighbors; bounded so a runaway entity doesn't
        # dump thousands of chunks.
        tasks = [
            self.store.entity_neighbors_chunks(e["entity_id"])
            for e in entities
        ]
        neighbor_lists = await asyncio.gather(*tasks, return_exceptions=True)

        chunks: list[dict[str, Any]] = []
        for entity, neighbors in zip(entities, neighbor_lists):
            if isinstance(neighbors, BaseException):
                logger.warning(
                    "graph_entity_neighbors_failed",
                    entity_id=entity.get("entity_id"),
                    error=str(neighbors),
                )
                continue
            count = 0
            for n in neighbors:
                if count >= self.max_neighbors_per_entity:
                    break
                chunks.append(
                    {
                        "chunk_id": n.get("chunk_id"),
                        "content": n.get("content"),
                        "title": n.get("title"),
                        "url": n.get("url"),
                        "source": n.get("source"),
                        # Neo4j cosine similarity, already normalized
                        "score": float(entity.get("score", 0.0)),
                        "via_entities": [entity["name"]],
                        "via_relations": [
                            r for r in (n.get("via_relations") or []) if r
                        ],
                        "retrieval_path": "graph_entity",
                    }
                )
                count += 1
        return chunks

    # ------------------------------------------------------------------
    # Relation path
    # ------------------------------------------------------------------

    async def _relation_search(self, query: str) -> list[dict[str, Any]]:
        """Fulltext search on relation keywords/description -> chunks via MENTIONED_IN.

        Each row already contains a chunk + a relation. We forward the
        Neo4j fulltext score as the chunk's score. Multiple relations can
        map to the same chunk; merge them in ``_merge``.
        """
        try:
            rows = await self.store.fulltext_search_relations(
                query, top_k=self.relation_top_k
            )
        except GraphStoreError as e:
            logger.warning("graph_fulltext_relations_failed", error=str(e))
            return []
        if not rows:
            return []

        chunks: list[dict[str, Any]] = []
        for r in rows:
            chunks.append(
                {
                    "chunk_id": r.get("chunk_id"),
                    "content": r.get("content"),
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "source": r.get("source"),
                    "score": float(r.get("score", 0.0)),
                    "via_entities": [
                        name
                        for name in (r.get("source_entity"), r.get("target_entity"))
                        if name
                    ],
                    "via_relations": [
                        {
                            "type": r.get("relation_type"),
                            "source": r.get("source_entity"),
                            "target": r.get("target_entity"),
                        }
                    ],
                    "retrieval_path": "graph_relation",
                }
            )
        return chunks

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def _merge(
        self,
        entity_chunks: list[dict[str, Any]],
        relation_chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Combine entity + relation chunks by chunk_id, averaging scores.

        A chunk hit by both paths is more relevant than one hit by only
        one. Average score (not sum) keeps the scale compatible with the
        Milvus path's cosine similarity.
        """
        by_chunk: dict[str, dict[str, Any]] = {}
        for chunk in entity_chunks + relation_chunks:
            cid = chunk.get("chunk_id")
            if not cid:
                continue
            existing = by_chunk.get(cid)
            if existing is None:
                by_chunk[cid] = {
                    "chunk_id": cid,
                    "content": chunk.get("content"),
                    "title": chunk.get("title"),
                    "url": chunk.get("url"),
                    "source": chunk.get("source"),
                    "score": chunk["score"],
                    "score_sum": chunk["score"],
                    "score_count": 1,
                    "via_entities": list(dict.fromkeys(chunk.get("via_entities") or [])),
                    "via_relations": list(chunk.get("via_relations") or []),
                    "retrieval_paths": {chunk.get("retrieval_path")},
                }
            else:
                existing["score_sum"] += chunk["score"]
                existing["score_count"] += 1
                for ent in chunk.get("via_entities") or []:
                    if ent not in existing["via_entities"]:
                        existing["via_entities"].append(ent)
                for rel in chunk.get("via_relations") or []:
                    if rel not in existing["via_relations"]:
                        existing["via_relations"].append(rel)
                existing["retrieval_paths"].add(chunk.get("retrieval_path"))

        # Finalize: average score, drop scratch fields
        for c in by_chunk.values():
            c["score"] = c["score_sum"] / c["score_count"]
            c["retrieval_path"] = "+".join(sorted(c["retrieval_paths"] - {None}))
            c.pop("score_sum", None)
            c.pop("score_count", None)
            c.pop("retrieval_paths", None)

        return sorted(by_chunk.values(), key=lambda x: -x["score"])


__all__ = ["GraphRetriever"]
