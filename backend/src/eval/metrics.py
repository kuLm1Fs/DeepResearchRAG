"""Evaluation metrics: keyword hit rate and citation coverage."""

from __future__ import annotations

import statistics
from typing import Iterable


def check_keyword_hits(results: list[dict], expected_keywords: list[str]) -> float:
    """Check what fraction of results contain at least one expected keyword.

    Returns a hit rate between 0.0 and 1.0.
    A result is a "hit" if any expected keyword appears (case-insensitive)
    in the title or content.
    """
    if not results or not expected_keywords:
        return 0.0

    keywords_lower = [kw.lower() for kw in expected_keywords]
    hits = 0

    for r in results:
        text = (r.get("title", "") + " " + r.get("content", "")).lower()
        if any(kw in text for kw in keywords_lower):
            hits += 1

    return hits / len(results)


def compute_citation_coverage(citations: list[dict]) -> dict:
    """Compute citation coverage statistics from claim-level citations.

    Each citation dict is expected to have a "support_level" key with
    values: "supported", "partial", or "unsupported".
    """
    total = len(citations)
    if total == 0:
        return {
            "total_claims": 0,
            "supported": 0,
            "partial": 0,
            "unsupported": 0,
            "coverage_rate": 0.0,
        }

    supported = sum(1 for c in citations if c.get("support_level") == "supported")
    partial = sum(1 for c in citations if c.get("support_level") == "partial")
    unsupported = sum(1 for c in citations if c.get("support_level") == "unsupported")

    return {
        "total_claims": total,
        "supported": supported,
        "partial": partial,
        "unsupported": unsupported,
        "coverage_rate": (supported + partial * 0.5) / total,
    }


# ---------------------------------------------------------------------------
# Phase 6: GraphRAG-specific metrics
# ---------------------------------------------------------------------------

def entity_recall(
    retrieved_entities: Iterable[str],
    expected_entities: Iterable[str],
) -> float:
    """Fraction of expected entities that were surfaced in the result set.

    Compares case-insensitively. Returns 0.0 if expected is empty.
    Used to compare the entity coverage of vector / graph / hybrid runs.
    """
    expected = {e.lower() for e in expected_entities if e}
    if not expected:
        return 0.0
    retrieved = {e.lower() for e in retrieved_entities if e}
    if not retrieved:
        return 0.0
    return len(expected & retrieved) / len(expected)


def graph_path_hit_rate(results: list[dict]) -> float:
    """Fraction of top-K chunks that came from the graph retrieval path.

    A chunk is from the graph path if it carries ``retrieval_path ==
    "graph"`` (set by ``GraphRetriever``). Vector/keyword/title chunks
    don't have this field. Returns 0.0 if no results.
    """
    if not results:
        return 0.0
    hits = sum(1 for r in results if r.get("retrieval_path") == "graph")
    return hits / len(results)


def latency_summary(latencies_ms: list[float]) -> dict:
    """Compute p50/p95/mean for a list of per-query latencies (ms)."""
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "mean": 0.0, "n": 0}
    sorted_lat = sorted(latencies_ms)
    n = len(sorted_lat)

    def pct(p: float) -> float:
        # Linear interpolation between the two nearest ranks.
        rank = (p / 100.0) * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        return sorted_lat[lo] * (1 - frac) + sorted_lat[hi] * frac

    return {
        "p50": round(pct(50), 2),
        "p95": round(pct(95), 2),
        "mean": round(statistics.mean(sorted_lat), 2),
        "n": n,
    }


def aggregate_graphrag_metrics(per_query: list[dict]) -> dict:
    """Roll up per-query metrics into a strategy-level summary.

    Each input row is expected to have: latency_ms, retrieved_entities,
    expected_entities, results. Returns a dict suitable for JSON output.
    """
    if not per_query:
        return {
            "queries": 0,
            "entity_recall_mean": 0.0,
            "graph_path_hit_rate_mean": 0.0,
            "latency": latency_summary([]),
        }

    recalls = [entity_recall(r.get("retrieved_entities", []), r.get("expected_entities", [])) for r in per_query]
    graph_hits = [graph_path_hit_rate(r.get("results", [])) for r in per_query]
    latencies = [float(r.get("latency_ms", 0.0)) for r in per_query]

    return {
        "queries": len(per_query),
        "entity_recall_mean": round(sum(recalls) / len(recalls), 4),
        "graph_path_hit_rate_mean": round(sum(graph_hits) / len(graph_hits), 4),
        "latency": latency_summary(latencies),
        # Source-count stat — useful for seeing whether the graph path
        # yields more or fewer top-K chunks than vector alone.
        "results_per_query_mean": round(
            sum(len(r.get("results", [])) for r in per_query) / len(per_query), 2
        ),
    }
