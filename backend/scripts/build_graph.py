"""CLI: build (or rebuild) the GraphRAG knowledge graph.

Usage:
    # Build from Milvus (re-process everything already in Milvus):
    python scripts/build_graph.py --from-milvus --limit 1000

    # Build from a JSONL file of articles:
    python scripts/build_graph.py --from-jsonl data/articles.jsonl

    # Force full rebuild (ignore idempotency ledger):
    python scripts/build_graph.py --from-milvus --force

    # Verify the graph is healthy:
    python scripts/build_graph.py --stats
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Make src/ importable when run as `python scripts/build_graph.py`
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT / "src"))
sys.path.insert(0, str(_BACKEND_ROOT))

from core import configure_logging, get_logger, settings  # noqa: E402

logger = get_logger(__name__)


async def build_from_milvus(limit: int | None = None, force: bool = False) -> dict[str, int]:
    """Public entrypoint: rebuild the graph from articles already in Milvus.

    Used by the /api/graph/rebuild endpoint. Kept public (not ``_build_…``)
    so it can be imported cleanly from the API layer without poking at a
    private function.
    """
    return await _build_from_milvus(limit=limit, force=force)


async def _build_from_milvus(limit: int | None, force: bool) -> dict[str, int]:
    """Pull articles from Milvus and run the graph builder.

    We read the same fields indexer.py uses, then build the graph.
    """
    from ingestion.pipeline import Pipeline  # type: ignore
    from pymilvus import connections

    # Connect to Milvus
    connections.connect(
        alias="default",
        host=settings.milvus_host,
        port=str(settings.milvus_port),
    )

    # We assume the collection is the default `news_articles` (matching
    # the project's indexer convention). Adjust the name if your deployment
    # uses something different.
    from pymilvus import Collection
    collection = Collection("news_articles")
    collection.load()

    iterator = collection.query_iterator(
        expr="content_hash != ''",
        output_fields=[
            "content_hash", "title", "content", "source", "language",
            "category", "published_at", "url", "external_id", "lead",
        ],
        limit=limit or 10000,
    )

    articles: list[dict[str, Any]] = []
    while True:
        batch = iterator.next()
        if not batch:
            break
        for row in batch:
            articles.append({
                "content_hash": row.get("content_hash", ""),
                "title": row.get("title", ""),
                "content": row.get("content", ""),
                "source": row.get("source", ""),
                "language": row.get("language", ""),
                "category": row.get("category", "news"),
                "published_at": row.get("published_at", 0),
                "url": row.get("url", ""),
                "external_id": row.get("external_id", ""),
                "lead": row.get("lead", ""),
            })
    iterator.close()

    logger.info("loaded_articles_from_milvus", count=len(articles))

    if not articles:
        return {"articles_in": 0, "articles_skipped": 0, "errors": 0}

    from graph import build_graph_for_articles

    if force:
        # Wipe the ledger to force reprocessing
        from graph.builder import _LEDGER_PATH
        if _LEDGER_PATH.exists():
            _LEDGER_PATH.unlink()
            logger.info("ledger_cleared_for_force_rebuild")

    return await build_graph_for_articles(articles, skip_existing=not force)


async def _build_from_jsonl(path: Path) -> dict[str, int]:
    """Build from a JSONL file. Each line is an article dict."""
    from graph import build_graph_for_articles

    articles = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                articles.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning("jsonl_skip_invalid_line", error=str(e))
    logger.info("loaded_articles_from_jsonl", count=len(articles), path=str(path))
    return await build_graph_for_articles(articles)


async def _print_stats() -> None:
    from graph import Neo4jStore
    async with Neo4jStore() as store:
        if not await store.health_check():
            print("Neo4j is not reachable. Check NEO4J_URI / NEO4J_PASSWORD.")
            return
        stats = await store.stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the GraphRAG knowledge graph."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--from-milvus", action="store_true",
        help="Read articles from Milvus (default source for production rebuilds)"
    )
    source.add_argument(
        "--from-jsonl", type=Path,
        help="Read articles from a JSONL file (each line = one article dict)"
    )
    source.add_argument(
        "--stats", action="store_true",
        help="Print Neo4j node/edge counts and exit"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of articles to process (default: all)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Ignore the idempotency ledger and re-process everything"
    )
    args = parser.parse_args()

    configure_logging()

    if args.stats:
        asyncio.run(_print_stats())
        return 0

    if not args.from_milvus and not args.from_jsonl:
        parser.error("Specify one of --from-milvus, --from-jsonl, or --stats")

    if args.from_milvus:
        stats = asyncio.run(_build_from_milvus(args.limit, args.force))
    else:
        stats = asyncio.run(_build_from_jsonl(args.from_jsonl))

    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
