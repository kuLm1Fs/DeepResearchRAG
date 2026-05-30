"""Article indexing helpers for RSS/HN/full-text ingestion."""
from __future__ import annotations

import time
import uuid
from typing import Any

from core import get_logger
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
) -> dict[str, int]:
    """Chunk articles, embed chunks, and insert them into Milvus."""
    store = store or MilvusStore()
    chunks: list[dict[str, Any]] = []

    for article in articles:
        parent_doc_id = article.get("content_hash") or str(uuid.uuid4())
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
                    "chunk_id": f"{parent_doc_id}:{chunk_index}",
                    "parent_doc_id": parent_doc_id,
                    "user_id": user_id,
                    "company_id": company_id,
                }
            )
            chunks.append(chunk)

    stats = {"articles": len(articles), "chunks": len(chunks), "inserted": 0}
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
    return stats
