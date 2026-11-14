"""Evaluation metrics for retrieval, finance evidence, and answer quality."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from typing import Any


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
# Finance evidence metrics
# ---------------------------------------------------------------------------

SOURCE_FIELDS = (
    "source_id",
    "doc_id",
    "document_id",
    "doc_name",
    "source",
    "url",
    "title",
    "file_name",
)


def normalise_match_text(value: Any) -> str:
    """Normalize text for loose source/evidence matching."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def result_source_candidates(result: dict[str, Any]) -> list[str]:
    """Extract normalized source identifiers from common result fields."""
    candidates = []
    for field in SOURCE_FIELDS:
        value = result.get(field)
        if value:
            candidates.append(normalise_match_text(value))
    return [candidate for candidate in candidates if candidate]


def _matches_source(result: dict[str, Any], expected_source: str) -> bool:
    expected = normalise_match_text(expected_source)
    if not expected:
        return False
    return any(
        expected in candidate or candidate in expected
        for candidate in result_source_candidates(result)
    )


def _matches_chunk_id(result: dict[str, Any], expected_chunk_id: str) -> bool:
    expected = str(expected_chunk_id or "")
    if not expected:
        return True
    return any(
        str(result.get(field, "") or "") == expected
        for field in ("chunk_id", "id", "external_id")
    )


def required_source_coverage_at_k(
    results: list[dict[str, Any]],
    required_sources: list[str],
    k: int,
) -> float:
    """Fraction of required source documents present in top-K results."""
    if not required_sources or k <= 0:
        return 0.0

    top_results = results[:k]
    hits = 0
    for source in required_sources:
        if any(_matches_source(result, source) for result in top_results):
            hits += 1
    return hits / len(required_sources)


def _result_text(result: dict[str, Any]) -> str:
    fields = ("title", "section", "content", "text", "summary")
    return " ".join(str(result.get(field, "")) for field in fields).lower()


def _evidence_matches(result: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Same constraints as ``evidence_hit_at_k`` for a single result/spec pair."""
    source_id = str(evidence.get("source_id", "") or "")
    chunk_id = str(evidence.get("chunk_id", "") or "")
    terms = [str(term).lower() for term in evidence.get("must_contain", []) if str(term)]
    section = str(evidence.get("section", "") or "").lower()

    if source_id and not _matches_source(result, source_id):
        return False
    text = _result_text(result)
    if section and section not in text:
        return False
    chunk_ok = bool(chunk_id) and _matches_chunk_id(result, chunk_id)
    terms_ok = bool(terms) and all(term in text for term in terms)
    return chunk_ok or terms_ok or (not chunk_id and not terms)


def evidence_gains(
    results: list[dict[str, Any]],
    expected_evidence: list[dict[str, Any]],
) -> list[int]:
    """How many still-unmatched evidence specs each result newly covers.

    The total of the gains equals the number of evidence specs matched by
    ``evidence_hit_at_k``. A result that covers two specs gets a gain of 2.
    """
    gains = [0] * len(results)
    if not expected_evidence:
        return gains

    unmatched = set(range(len(expected_evidence)))
    for index, result in enumerate(results):
        claimed = [
            ev_index
            for ev_index in unmatched
            if _evidence_matches(result, expected_evidence[ev_index])
        ]
        for ev_index in claimed:
            unmatched.discard(ev_index)
        gains[index] = len(claimed)
    return gains


def source_gains(results: list[dict[str, Any]], expected_sources: list[str]) -> list[int]:
    """How many still-unmatched expected sources each result newly covers."""
    gains = [0] * len(results)
    unmatched = {index for index, source in enumerate(expected_sources) if source}
    for index, result in enumerate(results):
        claimed = [
            source_index
            for source_index in unmatched
            if _matches_source(result, expected_sources[source_index])
        ]
        for source_index in claimed:
            unmatched.discard(source_index)
        gains[index] = len(claimed)
    return gains


def evidence_hit_at_k(
    results: list[dict[str, Any]],
    expected_evidence: list[dict[str, Any]],
    k: int,
) -> float:
    """Fraction of expected evidence specs matched by top-K chunks.

    Each evidence spec can include ``source_id``, ``must_contain`` terms, and
    an optional ``section`` hint. All provided constraints must match one
    retrieved result for the evidence item to count as hit.
    """
    if not expected_evidence or k <= 0:
        return 0.0
    return sum(evidence_gains(results[:k], expected_evidence)) / len(expected_evidence)


def _number_patterns(value: Any) -> list[str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return []

    patterns = {str(value).lower()}
    patterns.add(f"{number:g}".lower())
    patterns.add(f"{number:,.0f}".lower())
    if number.is_integer():
        patterns.add(str(int(number)))
    return [pattern for pattern in patterns if pattern]


def numeric_accuracy(answer: str, expected_numbers: list[dict[str, Any]]) -> float:
    """Score expected financial numbers found in the generated answer.

    A number item is correct when the answer contains the value plus any
    provided unit and period text. This deterministic metric is intentionally
    conservative; nuanced equivalence can be handled by LLM correctness.
    """
    if not expected_numbers:
        return 0.0

    answer_text = re.sub(r"\s+", " ", answer.lower())
    hits = 0
    for item in expected_numbers:
        value_ok = any(pattern in answer_text for pattern in _number_patterns(item.get("value")))
        unit = str(item.get("unit", "") or "").lower()
        period = str(item.get("period", "") or "").lower()
        unit_ok = not unit or all(part in answer_text for part in unit.split())
        period_ok = not period or period in answer_text
        if value_ok and unit_ok and period_ok:
            hits += 1

    return hits / len(expected_numbers)


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
