#!/usr/bin/env python3
"""
Download FinanceBench open-source data and ingest into Milvus.

Uses evidence_text_full_page as document content (no PDF download needed).

Usage:
    PYTHONPATH=src python scripts/seed_financebench.py
    PYTHONPATH=src python scripts/seed_financebench.py --limit 50
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from ingestion.indexer import index_articles

configure_logging()
logger = get_logger(__name__)

QUESTIONS_URL = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_open_source.jsonl"
META_URL = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_document_information.jsonl"

BATCH_SIZE = 16


def download_jsonl(url: str) -> list[dict[str, Any]]:
    """Download a JSONL file and return list of parsed dicts."""
    logger.info("downloading", url=url)
    with urllib.request.urlopen(url) as resp:
        lines = resp.read().decode("utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def build_records(
    questions: list[dict[str, Any]],
    meta: list[dict[str, Any]],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Build Milvus records from FinanceBench evidence data."""
    meta_by_doc = {m["doc_name"]: m for m in meta}
    records = []

    for q in questions[:limit] if limit else questions:
        doc_name = q["doc_name"]
        doc_meta = meta_by_doc.get(doc_name, {})
        doc_type = doc_meta.get("doc_type", "unknown")
        doc_link = doc_meta.get("doc_link", "")
        company = q.get("company", "")

        for evidence_index, ev in enumerate(q.get("evidence", [])):
            content = ev.get("evidence_text_full_page", "") or ev.get("evidence_text", "")
            if not content or len(content) < 50:
                continue

            page_num = ev.get("evidence_page_num", 0)
            title = f"{company} {doc_name} page {page_num} - {q['question'][:80]}"
            external_id = f"financebench:{doc_name}:p{page_num}:e{evidence_index}"
            content_hash = hashlib.sha256(
                f"{external_id}|{content}".encode()
            ).hexdigest()

            records.append({
                "title": title,
                "lead": q["question"],
                "content": content,
                "source": "FinanceBench",
                "language": "en",
                "category": doc_type,
                "published_at": 0,
                "url": doc_link,
                "content_hash": content_hash,
                "parent_doc_id": doc_name,
                "external_id": external_id,
            })

    return records


async def run(args: argparse.Namespace) -> int:
    questions = download_jsonl(QUESTIONS_URL)
    meta = download_jsonl(META_URL)
    logger.info("downloaded", questions=len(questions), documents=len(meta))

    records = build_records(questions, meta, args.limit)
    logger.info("records_built", count=len(records))

    if not records:
        print("No records to insert.")
        return 1

    stats = await index_articles(
        records,
        batch_size=BATCH_SIZE,
        build_graph=args.build_graph,
    )
    print(
        "\nDone. "
        f"Processed {stats['articles']} evidence records, "
        f"inserted {stats['inserted']} Milvus chunks."
    )
    if args.build_graph:
        print(
            "Graph build: "
            f"entities={stats['graph_entities']}, "
            f"relations={stats['graph_relations']}, "
            f"errors={stats['graph_errors']}."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Milvus with FinanceBench data")
    parser.add_argument("--limit", type=int, default=None, help="Max questions to process")
    parser.add_argument(
        "--build-graph",
        action="store_true",
        help="Also build Neo4j GraphRAG nodes/relations from the evidence chunks",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
