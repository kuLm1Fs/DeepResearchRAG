#!/usr/bin/env python3
"""
Evaluate retrieval quality by comparing semantic and multi-path retrieval.

Usage:
    PYTHONPATH=src python scripts/evaluate_retrieval.py
    PYTHONPATH=src python scripts/evaluate_retrieval.py --queries data/eval_queries.json
"""

import argparse
import asyncio
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Allow direct script execution from backend/ without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from retrieval import MultiPathRetriever
from vectorstore import MilvusStore, embed_texts_async

configure_logging()
logger = get_logger(__name__)

CATEGORIES = ["Sports", "Sci/Tech", "Business", "World"]
K_VALUES = [1, 3, 5, 10]
BATCH_SIZE = 10
TARGET_PRECISION_AT_5 = 0.8

TEST_QUERIES = [
    {"query": "football world cup results", "expected_categories": ["Sports"]},
    {"query": "basketball playoff scores", "expected_categories": ["Sports"]},
    {"query": "tennis grand slam champion", "expected_categories": ["Sports"]},
    {"query": "olympic games medal table", "expected_categories": ["Sports"]},
    {"query": "soccer transfer news", "expected_categories": ["Sports"]},
    {"query": "latest artificial intelligence breakthroughs", "expected_categories": ["Sci/Tech"]},
    {"query": "new smartphone technology release", "expected_categories": ["Sci/Tech"]},
    {"query": "cybersecurity data breach update", "expected_categories": ["Sci/Tech"]},
    {"query": "space exploration science discovery", "expected_categories": ["Sci/Tech"]},
    {"query": "software startup innovation", "expected_categories": ["Sci/Tech"]},
    {"query": "stock market earnings report", "expected_categories": ["Business"]},
    {"query": "central bank interest rate decision", "expected_categories": ["Business"]},
    {"query": "company merger acquisition deal", "expected_categories": ["Business"]},
    {"query": "global oil prices economy", "expected_categories": ["Business"]},
    {"query": "retail sales quarterly revenue", "expected_categories": ["Business"]},
    {"query": "international politics summit", "expected_categories": ["World"]},
    {"query": "election results government", "expected_categories": ["World"]},
    {"query": "war conflict peace talks", "expected_categories": ["World"]},
    {"query": "united nations climate agreement", "expected_categories": ["World"]},
    {"query": "diplomatic relations foreign policy", "expected_categories": ["World"]},
]

# Backward-compatible alias for callers that imported the old name.
DEFAULT_TEST_QUERIES = TEST_QUERIES


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    retrieved_k = retrieved[:k]
    return sum(1 for category in retrieved_k if category in relevant) / k


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    if not relevant or k <= 0:
        return 0.0
    retrieved_k = retrieved[:k]
    matched_categories = {category for category in retrieved_k if category in relevant}
    return len(matched_categories) / len(set(relevant))


def ndcg_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    if k <= 0:
        return 0.0

    relevance = [1.0 if category in relevant else 0.0 for category in retrieved[:k]]
    dcg = sum(rel / math.log2(rank + 2) for rank, rel in enumerate(relevance))
    ideal_relevance = [1.0] * k
    idcg = sum(rel / math.log2(rank + 2) for rank, rel in enumerate(ideal_relevance))
    return dcg / idcg if idcg else 0.0


def calculate_metrics(
    retrieved: list[str],
    relevant: list[str],
    k_values: list[int] | tuple[int, ...] = K_VALUES,
) -> dict[int, dict[str, float]]:
    return {
        k: {
            "precision": precision_at_k(retrieved, relevant, k),
            "recall": recall_at_k(retrieved, relevant, k),
            "ndcg": ndcg_at_k(retrieved, relevant, k),
        }
        for k in k_values
    }


def average_metric_dict(metric_dicts: list[dict[int, dict[str, float]]]) -> dict[int, dict[str, float]]:
    if not metric_dicts:
        return {k: {"precision": 0.0, "recall": 0.0, "ndcg": 0.0} for k in K_VALUES}

    averaged: dict[int, dict[str, float]] = {}
    for k in K_VALUES:
        averaged[k] = {
            name: sum(metrics[k][name] for metrics in metric_dicts) / len(metric_dicts)
            for name in ("precision", "recall", "ndcg")
        }
    return averaged


def category_precision_at_5(query_results: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for result in query_results:
        expected = result["expected_categories"]
        retrieved = result["retrieved_categories"]
        for category in expected:
            values[category].append(precision_at_k(retrieved, [category], 5))

    return {
        category: sum(values[category]) / len(values[category]) if values[category] else 0.0
        for category in CATEGORIES
    }


def summarize_results(
    query_results: list[dict[str, Any]],
    latencies_ms: list[float],
) -> dict[str, Any]:
    metrics = average_metric_dict([result["metrics"] for result in query_results])
    return {
        "avg_latency_ms": sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0,
        "metrics": metrics,
        "category_precision_at_5": category_precision_at_5(query_results),
    }


def extract_categories(results: list[dict[str, Any]]) -> list[str]:
    return [str(result.get("category", "")) for result in results]


async def evaluate_semantic(
    store: MilvusStore,
    test_queries: list[dict[str, Any]],
    top_k: int = 10,
) -> dict[str, Any]:
    query_results = []
    latencies_ms = []

    for start in range(0, len(test_queries), BATCH_SIZE):
        batch = test_queries[start:start + BATCH_SIZE]
        embedding_started = time.perf_counter()
        try:
            embeddings = await embed_texts_async([item.get("query", "") for item in batch])
        except Exception as exc:
            logger.error("semantic_embedding_failed", batch=start // BATCH_SIZE, error=str(exc))
            print(f"[ERROR] semantic embedding failed batch={start // BATCH_SIZE}: {exc}", file=sys.stderr)
            embeddings = []
        embedding_latency_ms = (time.perf_counter() - embedding_started) * 1000
        per_query_embedding_ms = embedding_latency_ms / len(batch) if batch else 0.0

        for index, item in enumerate(batch):
            query = item.get("query", "")
            expected = item.get("expected_categories", [])
            started = time.perf_counter()

            try:
                if index >= len(embeddings):
                    raise RuntimeError("embedding missing")
                embedding = embeddings[index]
                raw_results = store.search(query_embedding=embedding, top_k=top_k)
                retrieved_categories = extract_categories(raw_results)
                error = None
            except Exception as exc:
                logger.error("semantic_search_failed", query=query, error=str(exc))
                print(f"[ERROR] semantic search failed query={query!r}: {exc}", file=sys.stderr)
                raw_results = []
                retrieved_categories = []
                error = str(exc)

            latency_ms = per_query_embedding_ms + (time.perf_counter() - started) * 1000
            latencies_ms.append(latency_ms)
            query_results.append({
                "query": query,
                "expected_categories": expected,
                "retrieved_categories": retrieved_categories,
                "results": raw_results,
                "metrics": calculate_metrics(retrieved_categories, expected),
                "latency_ms": latency_ms,
                **({"error": error} if error else {}),
            })

    return {
        "name": "Semantic",
        "query_results": query_results,
        "summary": summarize_results(query_results, latencies_ms),
    }


async def evaluate_multipath(
    retriever: MultiPathRetriever,
    test_queries: list[dict[str, Any]],
    top_k: int = 10,
) -> dict[str, Any]:
    query_results = []
    latencies_ms = []

    for start in range(0, len(test_queries), BATCH_SIZE):
        batch = test_queries[start:start + BATCH_SIZE]

        for item in batch:
            query = item.get("query", "")
            expected = item.get("expected_categories", [])
            started = time.perf_counter()

            try:
                raw_results = await retriever.retrieve(query, top_k=top_k)
                retrieved_categories = extract_categories(raw_results)
                error = None
            except Exception as exc:
                logger.error("multipath_retrieve_failed", query=query, error=str(exc))
                print(f"[ERROR] multipath retrieve failed query={query!r}: {exc}", file=sys.stderr)
                raw_results = []
                retrieved_categories = []
                error = str(exc)

            latency_ms = (time.perf_counter() - started) * 1000
            latencies_ms.append(latency_ms)
            query_results.append({
                "query": query,
                "expected_categories": expected,
                "retrieved_categories": retrieved_categories,
                "results": raw_results,
                "metrics": calculate_metrics(retrieved_categories, expected),
                "latency_ms": latency_ms,
                **({"error": error} if error else {}),
            })

    return {
        "name": "MultiPath",
        "query_results": query_results,
        "summary": summarize_results(query_results, latencies_ms),
    }


def load_test_queries(file_path: Path | None) -> list[dict[str, Any]]:
    if file_path is None:
        return TEST_QUERIES

    if not file_path.exists():
        logger.warning("query_file_not_found", path=str(file_path), using_default=True)
        return TEST_QUERIES

    try:
        with open(file_path, encoding="utf-8") as file:
            queries = json.load(file)
        logger.info("test_queries_loaded", count=len(queries), path=str(file_path))
        return queries
    except Exception as exc:
        logger.error("query_file_load_failed", path=str(file_path), error=str(exc))
        return TEST_QUERIES


def resolve_backend_path(path: str | None, default: Path) -> Path:
    if path is None:
        return default
    given = Path(path)
    return given if given.is_absolute() else Path(__file__).parent.parent / given


def format_metric_row(k: int, metrics: dict[str, float]) -> str:
    marker = "  ◀" if k == 5 else ""
    return (
        f"  │  {k:<4} {metrics['precision']:<11.3f} "
        f"{metrics['recall']:<10.3f} {metrics['ndcg']:<.3f}{marker}"
    )


def print_strategy_report(title: str, result: dict[str, Any]) -> None:
    summary = result["summary"]
    print(f"\n  ┌─ {title}")
    print(f"  │  平均延迟: {summary['avg_latency_ms']:.0f}ms")
    print("  │  K    Precision    Recall     NDCG")
    print("  │  ────────────────────────────────────────")
    for k in K_VALUES:
        print(format_metric_row(k, summary["metrics"][k]))


def print_category_bars(title: str, category_precision: dict[str, float]) -> None:
    print(f"\n  {title} 分类别 Precision@5")
    for category in CATEGORIES:
        value = category_precision.get(category, 0.0)
        filled = round(value * 20)
        bar = "█" * filled + "░" * (20 - filled)
        print(f"  {category:<9} {bar} {value * 100:5.1f}%")


def print_report(results: dict[str, Any], output_file: Path) -> None:
    semantic = results["strategies"]["semantic"]
    multipath = results["strategies"]["multipath"]
    multipath_p5 = multipath["summary"]["metrics"][5]["precision"]

    print("\n" + "=" * 60)
    print("  RAG 检索质量评估报告")
    print("=" * 60)
    print(f"  测试查询数: {results['total_queries']}")
    print("  评估维度:   Precision / Recall / NDCG @ K=1,3,5,10")
    print("=" * 60)

    print_strategy_report("语义检索 (Semantic)", semantic)
    print_strategy_report("多路检索 (MultiPath)", multipath)
    print_category_bars("语义检索", semantic["summary"]["category_precision_at_5"])
    print_category_bars("多路检索", multipath["summary"]["category_precision_at_5"])

    print(f"\n  目标: Precision@5 >= {TARGET_PRECISION_AT_5:.1f}")
    print(f"  结果: {'✅ 通过' if multipath_p5 >= TARGET_PRECISION_AT_5 else '❌ 未通过'}")
    print(f"\n  详细结果已保存至: {output_file}")


async def run_evaluation(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    backend_dir = Path(__file__).parent.parent
    query_file = resolve_backend_path(args.queries, backend_dir / "data" / "eval_queries.json") if args.queries else None
    output_dir = resolve_backend_path(args.output, backend_dir / "data" / "eval_results")
    test_queries = load_test_queries(query_file)

    logger.info(
        "evaluation_started",
        query_file=str(query_file) if query_file else "builtin",
        output_dir=str(output_dir),
        query_count=len(test_queries),
    )

    store = MilvusStore()
    retriever = MultiPathRetriever(store)

    semantic = await evaluate_semantic(store, test_queries, top_k=max(K_VALUES))
    multipath = await evaluate_multipath(retriever, test_queries, top_k=max(K_VALUES))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{timestamp}.json"
    multipath_p5 = multipath["summary"]["metrics"][5]["precision"]
    output_data = {
        "timestamp": timestamp,
        "total_queries": len(test_queries),
        "k_values": K_VALUES,
        "target_precision_at_5": TARGET_PRECISION_AT_5,
        "passed": multipath_p5 >= TARGET_PRECISION_AT_5,
        "strategies": {
            "semantic": semantic,
            "multipath": multipath,
        },
    }

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(output_data, file, indent=2, ensure_ascii=False, default=str)

    return output_data, output_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality")
    parser.add_argument("--queries", type=str, default=None, help="Path to test queries JSON file")
    parser.add_argument("--output", type=str, default=None, help="Output directory for results")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        results, output_file = asyncio.run(run_evaluation(args))
    except Exception as exc:
        logger.error("evaluation_failed", error=str(exc))
        print(f"错误: 检索评估初始化失败: {exc}")
        return 1

    print_report(results, output_file)
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
