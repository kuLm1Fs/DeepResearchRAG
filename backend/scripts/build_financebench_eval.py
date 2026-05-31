#!/usr/bin/env python3
"""
Download FinanceBench and convert to eval dataset format.

Output: backend/data/eval_financebench.json (v2 format with gold_answer + evidence_texts)

Usage:
    PYTHONPATH=src python scripts/build_financebench_eval.py
    PYTHONPATH=src python scripts/build_financebench_eval.py --limit 50
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

QUESTIONS_URL = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_open_source.jsonl"
META_URL = "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_document_information.jsonl"

DIFFICULTY_MAP = {
    "metrics-generated": "easy",
    "domain-relevant": "medium",
    "novel-generated": "hard",
}


def download_jsonl(url: str) -> list[dict[str, Any]]:
    with urllib.request.urlopen(url) as resp:
        lines = resp.read().decode("utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def extract_keywords(question: str, company: str, doc_name: str) -> list[str]:
    """Extract expected keywords from question context."""
    keywords = []
    if company:
        keywords.append(company)
    # Add key terms from doc_name (e.g. "3M_2018_10K" -> ["3M", "2018", "10-K"])
    parts = doc_name.split("_")
    for p in parts:
        if p and len(p) > 1:
            keywords.append(p)
    # Add obvious financial terms from question
    financial_terms = [
        "revenue", "income", "profit", "loss", "earnings", "assets", "liabilities",
        "cash flow", "debt", "equity", "margin", "growth", "expense", "dividend",
        "operating", "net", "gross", "total", "fiscal", "quarter", "annual",
    ]
    q_lower = question.lower()
    for term in financial_terms:
        if term in q_lower:
            keywords.append(term)
    return list(set(keywords))[:8]


def build_eval_queries(
    questions: list[dict[str, Any]],
    meta: list[dict[str, Any]],
    limit: int | None,
) -> list[dict[str, Any]]:
    meta_by_doc = {m["doc_name"]: m for m in meta}
    queries = []

    for i, q in enumerate(questions[:limit] if limit else questions):
        doc_name = q["doc_name"]
        company = q.get("company", "")
        doc_meta = meta_by_doc.get(doc_name, {})
        doc_type = doc_meta.get("doc_type", "unknown")

        evidence_texts = [ev.get("evidence_text", "") for ev in q.get("evidence", []) if ev.get("evidence_text")]

        queries.append({
            "id": f"fb-{i + 1:03d}",
            "query": q["question"],
            "language": "en",
            "expected_keywords": extract_keywords(q["question"], company, doc_name),
            "gold_answer": q.get("answer", ""),
            "evidence_texts": evidence_texts,
            "doc_name": doc_name,
            "company": company,
            "doc_type": doc_type,
            "question_type": q.get("question_type", ""),
            "question_reasoning": q.get("question_reasoning"),
            "difficulty": DIFFICULTY_MAP.get(q.get("question_type", ""), "medium"),
        })

    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FinanceBench eval dataset")
    parser.add_argument("--limit", type=int, default=None, help="Max questions")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    questions = download_jsonl(QUESTIONS_URL)
    meta = download_jsonl(META_URL)
    logger.info("downloaded", questions=len(questions), documents=len(meta))

    queries = build_eval_queries(questions, meta, args.limit)

    output_path = Path(args.output) if args.output else Path(__file__).parent.parent / "data" / "eval_financebench.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = {
        "version": 2,
        "domain": "finance",
        "source": "FinanceBench",
        "description": "SEC filings QA benchmark (10-K, 10-Q, 8-K, earnings reports)",
        "queries": queries,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    # Stats
    difficulties = {}
    question_types = {}
    for q in queries:
        difficulties[q["difficulty"]] = difficulties.get(q["difficulty"], 0) + 1
        question_types[q["question_type"]] = question_types.get(q["question_type"], 0) + 1

    print(f"\nWrote {len(queries)} queries to {output_path}")
    print(f"  Difficulty: {difficulties}")
    print(f"  Question types: {question_types}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
