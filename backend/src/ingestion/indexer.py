"""Article indexing helpers for RSS/HN/full-text ingestion."""
from __future__ import annotations

import time
import uuid
from typing import Any

from core import get_logger, settings
from ingestion.chunker import chunk_article
from vectorstore import MilvusStore, embed_texts_async

logger = get_logger(__name__)

EMBEDDING_MAX_CHARS = 2000


async def index_articles(
    articles: list[dict[str, Any]],
    store: MilvusStore | None = None,
    batch_size: int = 50,
    user_id: str = "",
    company_id: str = "",
    build_graph: bool = True,
) -> dict[str, int]:
    """Chunk articles, embed chunks, insert into Milvus, then build the graph.

    Graph building is best-effort: any failure is logged and surfaced in
    ``stats["graph_errors"]`` so the caller can see it happened, but the
    vector insert is the source of truth and is not rolled back.
    """
    store = store or MilvusStore()
    chunks: list[dict[str, Any]] = []

    for article in articles:
        parent_doc_id = article.get("parent_doc_id") or article.get("content_hash") or str(uuid.uuid4())
        chunk_base_id = article.get("external_id") or parent_doc_id
        article_chunks = chunk_article(
            {
                "title": article.get("title", ""),
                "pub_time": article.get("pub_time", ""),
                "source": article.get("source", ""),
                "lead": article.get("lead", ""),
                "content": article.get("content", ""),
            },
            max_chars=3500,
        )
        for chunk in article_chunks:
            chunk_index = chunk.get("chunk_index", 0)
            chunk.update(
                {
                    "language": article.get("language", ""),
                    "category": article.get("category", "news"),
                    "published_at": int(article.get("published_at") or 0),
                    "url": article.get("url", ""),
                    "author": article.get("author") or article.get("hn_author", ""),
                    "external_id": article.get("external_id", ""),
                    "fetched_at": int(time.time()),
                    "chunk_id": f"{chunk_base_id}:{chunk_index}",
                    "parent_doc_id": parent_doc_id,
                    "user_id": user_id,
                    "company_id": company_id,
                }
            )
            chunks.append(chunk)

    stats = {
        "articles": len(articles),
        "chunks": len(chunks),
        "inserted": 0,
        "graph_entities": 0,
        "graph_relations": 0,
        "graph_errors": 0,
    }
    if not chunks:
        return stats

    texts = [chunk["content"][:EMBEDDING_MAX_CHARS] for chunk in chunks]
    embeddings = await embed_texts_async(texts, batch_size=batch_size)
    records = []
    for chunk, embedding in zip(chunks, embeddings):
        record = dict(chunk)
        record["embedding"] = embedding
        records.append(record)

    inserted_ids = store.insert(records)
    stats["inserted"] = len(inserted_ids)
    logger.info("articles_indexed", **stats)

    # Graph build is best-effort: vector path is authoritative.
    if build_graph and settings.graph_enabled and articles:
        try:
            # Lazy import: keeps neo4j out of the import-time graph for
            # environments that don't use the graph layer.
            from graph.builder import build_graph_for_articles

            graph_stats = await build_graph_for_articles(articles)
            stats["graph_entities"] = graph_stats.get("entities_upserted", 0)
            stats["graph_relations"] = graph_stats.get("relations_upserted", 0)
            logger.info("graph_build_attached", **graph_stats)
        except Exception as e:
            stats["graph_errors"] += 1
            logger.warning(
                "graph_build_skipped_after_index",
                error=str(e),
                error_type=type(e).__name__,
            )

    return stats
