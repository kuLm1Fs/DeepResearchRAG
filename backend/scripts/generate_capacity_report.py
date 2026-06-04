#!/usr/bin/env python
import argparse
import json
from pathlib import Path
from typing import Any


def build_capacity_report(
    locust_summary_path: Path,
    *,
    latency_budget_ms: int = 2000,
    error_rate_budget: float = 0.01,
) -> dict[str, Any]:
    summary = json.loads(locust_summary_path.read_text(encoding="utf-8"))
    routes = [_route_report(row, latency_budget_ms, error_rate_budget) for row in summary.get("stats", [])]
    routes = [route for route in routes if route["name"] != "Aggregated"]

    overall_status = "pass"
    if any(route["bottlenecks"] for route in routes):
        overall_status = "needs_capacity_work"

    return {
        "overall_status": overall_status,
        "latency_budget_ms": latency_budget_ms,
        "error_rate_budget": error_rate_budget,
        "routes": routes,
        "next_actions": _next_actions(routes),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Capacity Report",
        "",
        f"- Overall status: `{report['overall_status']}`",
        f"- P95 latency budget: `{report['latency_budget_ms']} ms`",
        f"- Error rate budget: `{report['error_rate_budget']:.2%}`",
        "",
        "| Route | Requests | RPS | P50 | P95 | P99 | Error Rate | Bottlenecks |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for route in report["routes"]:
        lines.append(
            "| {name} | {requests} | {rps:.2f} | {p50_ms:.0f} | {p95_ms:.0f} | "
            "{p99_ms:.0f} | {error_rate:.2%} | {bottlenecks} |".format(
                **route,
                bottlenecks=", ".join(route["bottlenecks"]) or "none",
            )
        )

    lines.extend(["", "## Next Actions"])
    for action in report["next_actions"]:
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def _route_report(
    row: dict[str, Any],
    latency_budget_ms: int,
    error_rate_budget: float,
) -> dict[str, Any]:
    requests = int(row.get("num_requests") or 0)
    failures = int(row.get("num_failures") or 0)
    error_rate = failures / requests if requests else 0.0
    p95_ms = float(row.get("response_time_percentile_0.95") or row.get("95%") or 0)
    p99_ms = float(row.get("response_time_percentile_0.99") or row.get("99%") or 0)

    bottlenecks = []
    if p95_ms > latency_budget_ms:
        bottlenecks.append("latency_p95_over_budget")
    if error_rate > error_rate_budget:
        bottlenecks.append("error_rate_over_budget")

    return {
        "name": row.get("name", "unknown"),
        "requests": requests,
        "failures": failures,
        "error_rate": round(error_rate, 6),
        "avg_ms": float(row.get("avg_response_time") or 0),
        "p50_ms": float(row.get("median_response_time") or row.get("50%") or 0),
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "rps": float(row.get("current_rps") or row.get("requests_per_second") or 0),
        "bottlenecks": bottlenecks,
    }


def _next_actions(routes: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    if any("latency_p95_over_budget" in route["bottlenecks"] for route in routes):
        actions.append("Break down p95 latency by LLM, retrieval paths, reranker, and database calls.")
    if any("error_rate_over_budget" in route["bottlenecks"] for route in routes):
        actions.append("Inspect errors by fault scenario and verify degradation policy coverage.")
    return actions or ["Keep the current capacity target and rerun after major dependency or prompt changes."]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a capacity report from Locust JSON stats.")
    parser.add_argument("summary", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/capacity_report.md"))
    parser.add_argument("--latency-budget-ms", type=int, default=2000)
    parser.add_argument("--error-rate-budget", type=float, default=0.01)
    args = parser.parse_args()

    report = build_capacity_report(
        args.summary,
        latency_budget_ms=args.latency_budget_ms,
        error_rate_budget=args.error_rate_budget,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
