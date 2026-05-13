#!/usr/bin/env python3
"""
RSS 全文采集 → MinIO 存储 → Chunk 切分 → Embedding → Milvus 导入

用法:
    cd /Users/poikoi/code/RAG/backend
    PYTHONPATH=src .venv/bin/python scripts/import_rss_pipeline.py --limit 10 --sources techcrunch,bbc

参数:
    --limit: 每个来源最多抓几条（默认 10）
    --sources: 逗号分隔的来源名称（techcrunch/theverge/bbc/36kr/sspai 等）
"""

import argparse
import asyncio
import sys
from itertools import islice
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from ingestion.rss_collector import RSSCollector
from ingestion.chunker import chunk_article
from storage import MinioStore
from vectorstore import ChunkStore, embed_texts_async

configure_logging()
logger = get_logger(__name__)
EMBEDDING_MAX_CHARS = 2000

# RSS 源名称映射（对应 RSSCollector 的 source_name 字段）
RSS_NAME_MAP = {
    "techcrunch": "TechCrunch",
    "theverge": "The Verge",
    "ars": "Ars Technica",
    "bbc": "BBC World",
    "reuters": "Reuters World",
    "36kr": "36氪",
    "sspai": "少数派",
    "tmtpost": "钛媒体",
    "ifanr": "爱范儿",
    "thepaper": "澎湃新闻",
}


async def process_articles(articles: list[dict], minio: MinioStore, chunk_store: ChunkStore) -> dict:
    """处理文章列表：MinIO存储 + chunk切分 + embed + 写入Milvus"""
    stats = {"total": len(articles), "stored": 0, "chunks": 0, "errors": 0}

    for article in articles:
        try:
            # 1. 上传 MinIO
            content_hash = article.get("content_hash", "")
            full_text = article.get("content", "") or article.get("full_text", "")
            if full_text and content_hash:
                minio.upload_article(content_hash, full_text)
                logger.info("minio_uploaded", hash=content_hash[:16])

            # 2. 切 chunk
            chunks = chunk_article(
                {
                    "title": article.get("title", ""),
                    "pub_time": article.get("pub_time", ""),
                    "source": article.get("source", ""),
                    "lead": article.get("lead", ""),
                    "content": full_text,
                },
                max_chars=3500,
            )
            logger.info("article_chunks", title=article.get("title", "")[:40], chunk_count=len(chunks))

            if not chunks:
                continue

            # 3. 批量 embed（batch_size=16）
            texts = [c["content"][:EMBEDDING_MAX_CHARS] for c in chunks]
            embeddings = await embed_texts_async(texts, batch_size=16)

            # 4. 写入 Milvus
            for chunk, embedding in zip(chunks, embeddings):
                chunk["embedding"] = embedding
                chunk_store.upsert_chunk(chunk)

            stats["stored"] += 1
            stats["chunks"] += len(chunks)
            logger.info("article_indexed", title=article.get("title", "")[:40], chunks=len(chunks))

        except Exception as e:
            stats["errors"] += 1
            logger.exception("article_process_failed", title=article.get("title", "")[:40], error=str(e))

    return stats


async def main():
    parser = argparse.ArgumentParser(description="RSS 全文采集 → MinIO + Chunk → Milvus")
    parser.add_argument("--limit", type=int, default=10, help="每个来源抓几条")
    parser.add_argument("--sources", type=str, default="techcrunch,bbc,36kr", help="来源列表，逗号分隔")
    parser.add_argument("--dry-run", action="store_true", help="只采集不写入")
    args = parser.parse_args()

    # 初始化组件
    collector = RSSCollector()
    minio = MinioStore()
    chunk_store = ChunkStore()

    # 解析来源
    source_names = [RSS_NAME_MAP.get(s.strip(), s.strip()) for s in args.sources.split(",")]
    logger.info("import_starting", sources=source_names, limit=args.limit)

    # 采集
    all_articles = []
    for source in source_names:
        try:
            source_config = next(r for r in collector.sources if r["name"] == source)
            articles = list(islice(collector.collect_from_source(
                url=source_config["url"],
                source_name=source,
                language=source_config["language"],
                category=source_config.get("category", "news"),
                fetch_full_text=True,
            ), args.limit))
            all_articles.extend(articles)
            logger.info("source_fetched", source=source, count=len(articles))
        except Exception as e:
            logger.exception("source_fetch_failed", source=source, error=str(e))

    logger.info("total_articles", count=len(all_articles))
    if not all_articles:
        print("没有采集到任何文章")
        return

    # 处理
    if args.dry_run:
        print(f"[Dry Run] 采集到 {len(all_articles)} 条文章，跳过写入")
        for a in all_articles:
            print(f"  - {a.get('title', '')[:60]}")
        return 0

    stats = await process_articles(all_articles, minio, chunk_store)

    print(f"\n{'='*50}")
    print(f"  RSS 导入完成")
    print(f"{'='*50}")
    print(f"  总文章数: {stats['total']}")
    print(f"  成功存储: {stats['stored']}")
    print(f"  Chunk 总数: {stats['chunks']}")
    print(f"  错误数: {stats['errors']}")
    print(f"  MinIO: {minio.stats()}")
    print(f"  Milvus: {chunk_store.stats()}")
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
