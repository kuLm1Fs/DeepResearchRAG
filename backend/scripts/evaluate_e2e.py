#!/usr/bin/env python3
"""
End-to-end RAG evaluation: retrieval + answer quality + citation coverage.

Runs each query through retrieval → generation → LLM-judge, then reports
aggregate metrics.  Designed to sit alongside (not replace) evaluate_retrieval.py.

Usage:
    PYTHONPATH=src python scripts/evaluate_e2e.py
    PYTHONPATH=src python scripts/evaluate_e2e.py --queries data/eval_tech_queries.json
    PYTHONPATH=src python scripts/evaluate_e2e.py --limit 10  # quick smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from core.config import settings
from eval.generator import generate_answer_only
from eval.judge import EvalJudge
from eval.metrics import check_keyword_hits, compute_citation_coverage
from retrieval import MultiPathRetriever
from vectorstore import MilvusStore

configure_logging()
logger = get_logger(__name__)

# ── Pass / fail thresholds ──────────────────────────────────────────
TARGETS = {
    "keyword_hit_rate": 0.7,
    "faithfulness": 3.5,
    "relevance": 3.5,
    "citation_coverage": 0.6,
}


# ── Helpers ─────────────────────────────────────────────────────────

def load_queries(path: Path) -> list[dict[str, Any]]:
    """Load v2 query file (with metadata header) or fall back to v1 list."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "queries" in data:
        return data["queries"]
    if isinstance(data, list):
        return data
    raise ValueError(f"Unrecognised query format in {path}")


def avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def group_by_difficulty(results: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        groups[r.get("difficulty", "unknown")].append(r)
    return groups


def difficulty_avg(results: list[dict], *keys: str) -> dict[str, dict[str, float]]:
    """Compute per-difficulty averages for nested metric keys."""
    groups = group_by_difficulty(results)
    out: dict[str, dict[str, float]] = {}
    for diff, items in sorted(groups.items()):
        out[diff] = {}
        for key_path in keys:
            parts = key_path.split(".")
            vals = []
            for item in items:
                obj = item
                for p in parts:
                    obj = obj.get(p, {}) if isinstance(obj, dict) else {}
                if isinstance(obj, (int, float)):
                    vals.append(float(obj))
            out[diff][parts[-1]] = avg(vals)
    return out


# ── Single-query evaluation ────────────────────────────────────────

async def evaluate_single(
    query_item: dict[str, Any],
    retriever: MultiPathRetriever,
    judge: EvalJudge,
) -> dict[str, Any]:
    """Evaluate one query end-to-end."""
    query = query_item["query"]
    expected_kw = query_item.get("expected_keywords", [])
    difficulty = query_item.get("difficulty", "unknown")

    result: dict[str, Any] = {
        "query_id": query_item.get("id", ""),
        "query": query,
        "language": query_item.get("language", "en"),
        "difficulty": difficulty,
    }

    # ── 1. Retrieval ────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        retrieval_results = await retriever.retrieve(query, top_k=5)
    except Exception as e:
        logger.error("retrieval_failed", query=query, error=str(e))
        result["error"] = f"retrieval: {e}"
        return result
    retrieval_ms = (time.perf_counter() - t0) * 1000

    result["retrieval"] = {
        "keyword_hit_rate": check_keyword_hits(retrieval_results, expected_kw),
        "result_count": len(retrieval_results),
        "latency_ms": round(retrieval_ms),
    }

    # ── 2. Answer generation ────────────────────────────────────────
    t1 = time.perf_counter()
    try:
        answer, sources, citations = await generate_answer_only(query, retrieval_results)
    except Exception as e:
        logger.error("generation_failed", query=query, error=str(e))
        result["error"] = f"generation: {e}"
        return result
    generation_ms = (time.perf_counter() - t1) * 1000

    result["answer_text"] = answer[:500]  # truncate for JSON size
    result["generation"] = {"latency_ms": round(generation_ms)}

    # ── 3. Citation coverage ────────────────────────────────────────
    result["citations"] = compute_citation_coverage(citations)

    # ── 4. LLM-as-judge ────────────────────────────────────────────
    t2 = time.perf_counter()
    gold_answer = query_item.get("gold_answer")
    judge_tasks = [
        judge.judge_faithfulness(query, answer, sources),
        judge.judge_relevance(query, answer),
    ]
    if gold_answer:
        judge_tasks.append(judge.judge_correctness(query, answer, gold_answer))

    judge_results = await asyncio.gather(*judge_tasks)
    judge_ms = (time.perf_counter() - t2) * 1000

    result["judge"] = {
        "faithfulness": judge_results[0],
        "relevance": judge_results[1],
        "latency_ms": round(judge_ms),
    }
    if gold_answer and len(judge_results) > 2:
        result["judge"]["correctness"] = judge_results[2]

    result["total_latency_ms"] = round(retrieval_ms + generation_ms + judge_ms)
    return result


# ── Batch runner ────────────────────────────────────────────────────

async def run_evaluation(
    queries: list[dict[str, Any]],
    concurrency: int = 3,
) -> dict[str, Any]:
    """Run all queries with bounded concurrency."""
    store = MilvusStore()
    retriever = MultiPathRetriever(store)
    judge = EvalJudge()

    sem = asyncio.Semaphore(concurrency)
    all_results: list[dict[str, Any]] = []
    errors = 0

    async def _run(item: dict) -> dict[str, Any]:
        nonlocal errors
        async with sem:
            try:
                return await evaluate_single(item, retriever, judge)
            except Exception as e:
                logger.error("eval_unhandled", query=item.get("query"), error=str(e))
                errors += 1
                return {"query_id": item.get("id", ""), "query": item.get("query"), "error": str(e)}

    tasks = [_run(q) for q in queries]
    all_results = await asyncio.gather(*tasks)

    # ── Aggregate ───────────────────────────────────────────────────
    valid = [r for r in all_results if "error" not in r]
    faith_scores = [r["judge"]["faithfulness"]["score"] for r in valid if "judge" in r]
    rel_scores = [r["judge"]["relevance"]["score"] for r in valid if "judge" in r]
    corr_scores = [r["judge"]["correctness"]["score"] for r in valid if "judge" in r and "correctness" in r.get("judge", {})]
    kw_rates = [r["retrieval"]["keyword_hit_rate"] for r in valid if "retrieval" in r]
    cov_rates = [r["citations"]["coverage_rate"] for r in valid if "citations" in r]
    latencies = [r["total_latency_ms"] for r in valid if "total_latency_ms" in r]

    avg_faith = avg(faith_scores)
    avg_rel = avg(rel_scores)
    avg_corr = avg(corr_scores) if corr_scores else None
    avg_kw = avg(kw_rates)
    avg_cov = avg(cov_rates)

    passed = (
        avg_kw >= TARGETS["keyword_hit_rate"]
        and avg_faith >= TARGETS["faithfulness"]
        and avg_rel >= TARGETS["relevance"]
        and avg_cov >= TARGETS["citation_coverage"]
    )

    answer_section: dict[str, Any] = {
        "avg_faithfulness": round(avg_faith, 2),
        "avg_relevance": round(avg_rel, 2),
        "faithfulness_by_difficulty": {
            d: round(avg([r["judge"]["faithfulness"]["score"] for r in items if "judge" in r]), 2)
            for d, items in group_by_difficulty(valid).items()
        },
        "relevance_by_difficulty": {
            d: round(avg([r["judge"]["relevance"]["score"] for r in items if "judge" in r]), 2)
            for d, items in group_by_difficulty(valid).items()
        },
    }
    if avg_corr is not None:
        answer_section["avg_correctness"] = round(avg_corr, 2)
        answer_section["correctness_by_difficulty"] = {
            d: round(avg([r["judge"]["correctness"]["score"] for r in items if "judge" in r and "correctness" in r.get("judge", {})]), 2)
            for d, items in group_by_difficulty(valid).items()
        }

    summary = {
        "total_queries": len(queries),
        "completed": len(valid),
        "errors": errors,
        "retrieval": {
            "avg_keyword_hit_rate": round(avg_kw, 3),
            "keyword_hit_rate_by_difficulty": {
                d: round(avg([r["retrieval"]["keyword_hit_rate"] for r in items if "retrieval" in r]), 3)
                for d, items in group_by_difficulty(valid).items()
            },
        },
        "answer": answer_section,
        "citations": {
            "avg_coverage_rate": round(avg_cov, 3),
            "avg_supported_claims": round(
                avg([r["citations"]["supported"] for r in valid if "citations" in r]), 1
            ),
        },
        "latency": {
            "avg_retrieval_ms": round(avg([r["retrieval"]["latency_ms"] for r in valid if "retrieval" in r])),
            "avg_generation_ms": round(avg([r["generation"]["latency_ms"] for r in valid if "generation" in r])),
            "avg_judge_ms": round(avg([r["judge"]["latency_ms"] for r in valid if "judge" in r])),
            "avg_total_ms": round(avg(latencies)),
        },
    }

    return {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "domain": "finance",
        "passed": passed,
        "targets": TARGETS,
        "summary": summary,
        "query_results": all_results,
    }


# ── Report printer ──────────────────────────────────────────────────

def print_report(results: dict[str, Any]) -> None:
    s = results["summary"]
    t = results["targets"]

    def _status(actual: float, target: float) -> str:
        return "pass" if actual >= target else "FAIL"

    print("\n" + "=" * 60)
    print("  RAG End-to-End Evaluation Report")
    print("=" * 60)
    print(f"  Queries: {s['completed']}/{s['total_queries']} completed, {s['errors']} errors")
    print("=" * 60)

    print("\n  Retrieval")
    r = s["retrieval"]
    print(f"    Keyword hit rate:  {r['avg_keyword_hit_rate']:.3f}  (target {t['keyword_hit_rate']})  [{_status(r['avg_keyword_hit_rate'], t['keyword_hit_rate'])}]")
    for diff, val in sorted(r.get("keyword_hit_rate_by_difficulty", {}).items()):
        print(f"      {diff}: {val:.3f}")

    print("\n  Answer Quality (LLM-as-Judge, 1-5 scale)")
    a = s["answer"]
    print(f"    Faithfulness:      {a['avg_faithfulness']:.2f}  (target {t['faithfulness']})  [{_status(a['avg_faithfulness'], t['faithfulness'])}]")
    for diff, val in sorted(a.get("faithfulness_by_difficulty", {}).items()):
        print(f"      {diff}: {val:.2f}")
    print(f"    Relevance:         {a['avg_relevance']:.2f}  (target {t['relevance']})  [{_status(a['avg_relevance'], t['relevance'])}]")
    for diff, val in sorted(a.get("relevance_by_difficulty", {}).items()):
        print(f"      {diff}: {val:.2f}")

    print("\n  Citations")
    c = s["citations"]
    print(f"    Coverage rate:     {c['avg_coverage_rate']:.3f}  (target {t['citation_coverage']})  [{_status(c['avg_coverage_rate'], t['citation_coverage'])}]")
    print(f"    Avg supported:     {c['avg_supported_claims']}")

    print("\n  Latency")
    l = s["latency"]
    print(f"    Retrieval:   {l['avg_retrieval_ms']}ms")
    print(f"    Generation:  {l['avg_generation_ms']}ms")
    print(f"    Judge:       {l['avg_judge_ms']}ms")
    print(f"    Total:       {l['avg_total_ms']}ms")

    print(f"\n  Result: {'PASS' if results['passed'] else 'FAIL'}")
    print("=" * 60)


# ── CLI ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="End-to-end RAG evaluation")
    p.add_argument("--queries", type=str, default=None, help="Path to query JSON file")
    p.add_argument("--output", type=str, default=None, help="Output directory")
    p.add_argument("--limit", type=int, default=None, help="Limit number of queries (for smoke tests)")
    p.add_argument("--concurrency", type=int, default=3, help="Max concurrent evaluations")
    return p


def main() -> int:
    args = build_parser().parse_args()
    backend_dir = Path(__file__).parent.parent

    query_path = Path(args.queries) if args.queries else backend_dir / "data" / "eval_tech_queries.json"
    if not query_path.is_absolute():
        query_path = backend_dir / query_path

    queries = load_queries(query_path)
    if args.limit:
        queries = queries[: args.limit]

    print(f"Loaded {len(queries)} queries from {query_path}")
    print(f"Concurrency: {args.concurrency}")
    print(f"LLM provider: {settings.llm_provider} / {settings.llm_model}")
    print("Running evaluation...\n")

    try:
        results = asyncio.run(run_evaluation(queries, concurrency=args.concurrency))
    except Exception as exc:
        logger.error("evaluation_failed", error=str(exc))
        print(f"\nFATAL: {exc}", file=sys.stderr)
        return 1

    # Save results
    output_dir = Path(args.output) if args.output else backend_dir / "data" / "eval_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"e2e_{results['timestamp']}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print_report(results)
    print(f"\n  Results saved to: {output_file}")

    return 0 if results["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
