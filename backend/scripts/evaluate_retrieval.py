#!/usr/bin/env python3
"""Evaluate retrieval quality."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger, settings
from vectorstore import MilvusStore
from retrieval import MultiPathRetriever

configure_logging()
logger = get_logger(__name__)

# Test queries with expected relevant categories
TEST_QUERIES = [
    ("sports news", ["Sports"]),
    ("business economy", ["Business"]),
    ("technology AI", ["Sci/Tech"]),
    ("world politics", ["World"]),
    ("science discoveries", ["Sci/Tech"]),
]


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    if k == 0:
        return 0.0
    retrieved_k = retrieved[:k]
    return len([r for r in retrieved_k if r in relevant]) / k


def main():
    store = MilvusStore()
    retriever = MultiPathRetriever(store)

    results = []
    for query, expected_categories in TEST_QUERIES:
        retrieved = retriever.retrieve(query, top_k=5)
        retrieved_categories = [r.get("category", "") for r in retrieved]
        p5 = precision_at_k(retrieved_categories, expected_categories, 5)

        results.append({
            "query": query,
            "expected": expected_categories,
            "retrieved": retrieved_categories,
            "precision@5": p5,
        })

        logger.info("query_evaluated",
            query=query,
            precision=p5,
            retrieved=retrieved_categories,
        )

    avg_precision = sum(r["precision@5"] for r in results) / len(results)
    logger.info("evaluation_completed", avg_precision=avg_precision)

    # Save results
    output_dir = settings.eval_results_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{datetime.now().date()}.json"

    with open(output_file, "w") as f:
        json.dump({"results": results, "avg_precision@5": avg_precision}, f, indent=2)

    print(f"\nResults saved to {output_file}")
    print(f"Average Precision@5: {avg_precision:.2f}")

    return avg_precision >= 0.8


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)