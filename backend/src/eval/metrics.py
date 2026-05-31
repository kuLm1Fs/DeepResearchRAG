"""Evaluation metrics: keyword hit rate and citation coverage."""

from __future__ import annotations


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
