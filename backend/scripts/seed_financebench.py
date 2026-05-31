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
import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from vectorstore import MilvusStore, embed_texts

configure_logging()
logger = get_logger(__name__)

QUESTIONS_URL = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_open_source.jsonl"
META_URL = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_document_information.jsonl"

BATCH_SIZE = 50


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

        for ev in q.get("evidence", []):
            content = ev.get("evidence_text_full_page", "") or ev.get("evidence_text", "")
            if not content or len(content) < 50:
                continue

            title = f"{company} {doc_name} - {q['question'][:80]}"
            content_hash = hashlib.sha256(f"{title}|{content[:500]}".encode()).hexdigest()

            records.append({
                "title": title,
                "content": content,
                "source": "FinanceBench",
                "language": "en",
                "category": doc_type,
                "published_at": 0,
                "url": doc_link,
                "content_hash": content_hash,
                "parent_doc_id": doc_name,
                "chunk_id": f"{doc_name}:{ev.get('evidence_page_num', 0)}",
            })

    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Milvus with FinanceBench data")
    parser.add_argument("--limit", type=int, default=None, help="Max questions to process")
    args = parser.parse_args()

    # Download
    questions = download_jsonl(QUESTIONS_URL)
    meta = download_jsonl(META_URL)
    logger.info("downloaded", questions=len(questions), documents=len(meta))

    # Build records
    records = build_records(questions, meta, args.limit)
    logger.info("records_built", count=len(records))

    if not records:
        print("No records to insert.")
        return 1

    # Insert into Milvus
    store = MilvusStore()

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        contents = [r["content"] for r in batch]
        embeddings = embed_texts(contents)
        for r, emb in zip(batch, embeddings):
            r["embedding"] = emb
        store.insert(batch)
        logger.info("inserted_batch", batch=i // BATCH_SIZE + 1, count=len(batch))

    print(f"\nDone. Inserted {len(records)} evidence chunks from {len(questions[:args.limit or len(questions)])} questions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
