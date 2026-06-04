#!/usr/bin/env python3
"""Phase 6: compare vector / graph / hybrid retrieval strategies on a fixed
query set and emit a JSON + markdown report.

The goal isn't statistical significance — it's a sanity check that the
graph path is *contributing* (i.e. surfacing chunks that pure vector
recall misses, or grounding more named entities). If hybrid loses to
vector on this eval, the routing rules in Phase 4 deserve a second look.

What this script measures
-------------------------
  * entity_recall:        fraction of expected entities surfaced
  * graph_path_hit_rate:  fraction of top-K chunks that came from graph
  * results_per_query:    mean top-K count
  * latency p50 / p95 / mean (ms)

Usage
-----
  PYTHONPATH=src python scripts/evaluate_graphrag.py \\
      --queries data/eval_queries_graphrag.json \\
      --output  data/eval_results/graphrag_comparison_$(date +%F).json

If ``--queries`` isn't given, a small built-in set is used (so the
script is useful out of the box for smoke testing). The expected
entities list is hand-curated; the score is a "does the strategy
surface at least the canonical entity names?" check.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow direct script execution from backend/ without requiring PYTHONPATH.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT / "src"))
sys.path.insert(0, str(_BACKEND_ROOT))

from core import configure_logging, get_logger  # noqa: E402

configure_logging()
logger = get_logger(__name__)

# Built-in fallback query set: 8 hand-curated financial queries that
# exercise entity disambiguation, multi-entity relations, and global
# topics. Each has a list of expected entity names — the entity_recall
# metric asks "did the strategy surface these?".
DEFAULT_QUERIES: list[dict] = [
    {
        "query": "苹果公司的主要竞争对手",
        "expected_entities": ["苹果", "三星", "华为"],
        "type": "comparison",
    },
    {
        "query": "TSMC 的客户包括哪些公司",
        "expected_entities": ["TSMC", "苹果", "英伟达"],
        "type": "factual",
    },
    {
        "query": "2025年半导体行业整体趋势",
        "expected_entities": ["半导体"],
        "type": "summary",
    },
    {
        "query": "英伟达和台积电的合作关系",
        "expected_entities": ["英伟达", "台积电"],
        "type": "comparison",
    },
    {
        "query": "美联储最近的利率决策",
        "expected_entities": ["美联储"],
        "type": "factual",
    },
    {
        "query": "OpenAI 的主要投资方是谁",
        "expected_entities": ["OpenAI", "微软"],
        "type": "factual",
    },
    {
        "query": "电动汽车市场的关键参与者",
        "expected_entities": ["特斯拉", "比亚迪"],
        "type": "summary",
    },
    {
        "query": "亚马逊和谷歌在云计算领域的竞争",
        "expected_entities": ["亚马逊", "谷歌"],
        "type": "comparison",
    },
]


async def _run_one(query: str, strategy: str, top_k: int) -> dict:
    """Run a single query with a forced strategy. Returns a per-query row.

    We invoke ``run_agent`` directly (not the HTTP layer) so the script
    can run without an ASGI server, and so we can pin the strategy
    without going through the API. The latency we measure is end-to-end
    agent time, not just retrieval — that matches what the user
    actually feels.
    """
    from agent import run_agent  # late import: pulls in langgraph etc.

    started = time.perf_counter()
    try:
        result = await run_agent(
            query=query,
            trace_id=f"eval_{strategy}_{int(started * 1000)}",
            top_k=top_k,
            forced_strategy=strategy,
        )
        latency_ms = (time.perf_counter() - started) * 1000
    except Exception as exc:  # noqa: BLE001
        logger.error("eval_query_failed", strategy=strategy, error=str(exc))
        return {
            "error": str(exc),
            "latency_ms": 0.0,
            "results": [],
            "retrieved_entities": [],
        }

    retrieval_results = result.get("retrieval_results", []) or []
    # Entities surfaced by the graph path come via via_entities on each chunk.
    retrieved_entities: list[str] = []
    for r in retrieval_results:
        for ent in r.get("via_entities") or []:
            if ent and ent not in retrieved_entities:
                retrieved_entities.append(ent)

    return {
        "latency_ms": round(latency_ms, 2),
        "results": retrieval_results,
        "retrieved_entities": retrieved_entities,
        "answer": result.get("answer", ""),
        "graph_facts": result.get("graph_facts", {}),
    }


async def _evaluate(queries: list[dict], strategies: list[str], top_k: int) -> dict:
    """Run every query under every strategy, collect per-row metrics."""
    rows: dict[str, list[dict]] = defaultdict(list)
    total = len(queries) * len(strategies)
    done = 0
    for q in queries:
        for strat in strategies:
            done += 1
            logger.info(
                "eval_progress",
                done=done,
                total=total,
                query=q["query"][:40],
                strategy=strat,
            )
            row = await _run_one(q["query"], strat, top_k)
            row["query"] = q["query"]
            row["expected_entities"] = q.get("expected_entities", [])
            row["type"] = q.get("type", "")
            rows[strat].append(row)

    return rows


def _summarize(rows: dict[str, list[dict]]) -> dict:
    """Compute strategy-level summaries from per-row records."""
    from eval.metrics import (
        aggregate_graphrag_metrics,
        entity_recall,
    )

    summary: dict[str, dict] = {}
    for strat, rs in rows.items():
        summary[strat] = aggregate_graphrag_metrics(rs)
        # Per-strategy recall histogram for the markdown report
        summary[strat]["per_query_recall"] = [
            round(entity_recall(r.get("retrieved_entities", []), r.get("expected_entities", [])), 3)
            for r in rs
        ]
    return summary


def _markdown_report(queries: list[dict], summary: dict) -> str:
    """Render a human-readable summary table for the terminal."""
    lines: list[str] = []
    lines.append("# GraphRAG strategy comparison\n")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat()}_\n")
    lines.append(f"_Queries: {len(queries)}_\n\n")

    # Strategy table
    lines.append("| Strategy | Entity recall | Graph hit rate | p50 (ms) | p95 (ms) | Results/query |\n")
    lines.append("|----------|---------------|----------------|----------|----------|---------------|\n")
    for strat, m in summary.items():
        lat = m["latency"]
        lines.append(
            f"| `{strat}` "
            f"| {m['entity_recall_mean']:.1%} "
            f"| {m['graph_path_hit_rate_mean']:.1%} "
            f"| {lat['p50']:.0f} "
            f"| {lat['p95']:.0f} "
            f"| {m['results_per_query_mean']:.1f} |\n"
        )

    # Per-query recall by strategy — useful for spotting queries where
    # one strategy diverges from the others.
    lines.append("\n## Per-query entity recall\n")
    lines.append("| Query | Type | " + " | ".join(summary.keys()) + " |\n")
    lines.append("|" + "---|" * (2 + len(summary)) + "\n")
    for i, q in enumerate(queries):
        cells = [q["query"][:40], q.get("type", "")]
        for strat in summary:
            recalls = summary[strat]["per_query_recall"]
            cells.append(f"{recalls[i]:.0%}" if i < len(recalls) else "-")
        lines.append("| " + " | ".join(cells) + " |\n")

    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare vector / graph / hybrid retrieval strategies."
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help="Path to a JSON array of {query, expected_entities[]} objects. "
        "Falls back to the built-in 8-query demo set.",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=["vector", "graph", "hybrid"],
        choices=["vector", "graph", "hybrid"],
        help="Strategies to evaluate (default: all three).",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="top_k to use for each retrieval call (default 5).",
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("data/eval_results/graphrag_comparison.json"),
        help="Where to write the JSON + markdown report.",
    )
    args = parser.parse_args()

    if args.queries:
        with open(args.queries) as f:
            queries = json.load(f)
        logger.info("loaded_queries", path=str(args.queries), n=len(queries))
    else:
        queries = DEFAULT_QUERIES
        logger.info("using_default_queries", n=len(queries))

    rows = asyncio.run(_evaluate(queries, args.strategies, args.top_k))
    summary = _summarize(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "summary": summary,
        "raw": rows,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    md_path = args.output.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_markdown_report(queries, summary))

    logger.info(
        "eval_written",
        json=str(args.output),
        markdown=str(md_path),
    )
    print(_markdown_report(queries, summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
