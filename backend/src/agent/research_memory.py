"""Research memory, evidence trace, and delivery quality helpers."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


def build_evidence_trace(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace = []
    for index, item in enumerate(evidence, start=1):
        trace.append(
            {
                "evidence_id": f"E{index:03d}",
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "published_at": item.get("published_at"),
                "score": float(item.get("rerank_score", item.get("fused_score", item.get("score", 0.0))) or 0.0),
                "snippet": (item.get("content", "") or "")[:300],
            }
        )
    return trace


def build_quality_report(
    evidence: list[dict[str, Any]],
    check_result: dict[str, Any] | None,
    gaps: list[str],
) -> dict[str, Any]:
    check_data = check_result or {}
    sources = [item.get("source", "unknown") for item in evidence if item.get("source")]
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    recent_count = 0
    for item in evidence:
        published_at = int(item.get("published_at") or 0)
        if published_at and now_ts - published_at <= 90 * 24 * 3600:
            recent_count += 1

    source_counts = Counter(sources)
    return {
        "evidence_coverage": float(check_data.get("coverage", 0.0) or 0.0),
        "source_diversity": {
            "unique_sources": len(source_counts),
            "total_evidence": len(evidence),
            "sources": dict(source_counts),
        },
        "freshness": {
            "recent_90d_count": recent_count,
            "recent_90d_ratio": recent_count / len(evidence) if evidence else 0.0,
        },
        "credibility": {
            "issues": check_data.get("credibility_issues", []),
            "conflicts": check_data.get("conflicts", []),
        },
        "gaps": gaps or check_data.get("gaps", []),
    }


def assemble_research_memory(state: dict[str, Any]) -> dict[str, Any]:
    evidence = state.get("evidence", [])
    check_result = state.get("check_result") or {}
    gaps = state.get("gaps", [])
    return {
        "query": state.get("query", ""),
        "plan": state.get("plan"),
        "current_step": state.get("current_step"),
        "tool_call_count": state.get("tool_call_count", 0),
        "max_tool_calls": state.get("max_tool_calls", 20),
        "evidence_trace": build_evidence_trace(evidence),
        "analysis": state.get("analysis"),
        "quality_report": build_quality_report(evidence, check_result, gaps),
        "gaps": gaps,
        "conflicts": state.get("conflicts", []),
    }
