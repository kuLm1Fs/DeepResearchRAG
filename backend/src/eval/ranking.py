"""Ranking metrics for retrieval ablation.

Gains are non-negative integers. A positive gain means that rank newly
covers one or more labeled evidence items (or source ids, when a case has
no evidence list). Hit / MRR treat any positive gain as relevant. Recall
sums gains, so one chunk that covers two evidence items counts twice.
nDCG uses linear gain and is capped at 1.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .metrics import evidence_gains, source_gains

METRIC_KEYS: tuple[str, ...] = (
    "hit@1",
    "hit@3",
    "hit@5",
    "recall@5",
    "mrr@10",
    "ndcg@10",
)


def hit_at_k(gains: Sequence[int], k: int) -> float:
    if k <= 0:
        return 0.0
    return 1.0 if any(gain > 0 for gain in gains[:k]) else 0.0


def recall_at_k(gains: Sequence[int], relevant_count: int, k: int) -> float:
    if relevant_count <= 0 or k <= 0:
        return 0.0
    return sum(gains[:k]) / relevant_count


def mrr_at_k(gains: Sequence[int], k: int) -> float:
    if k <= 0:
        return 0.0
    for rank, gain in enumerate(gains[:k], start=1):
        if gain > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(gains: Sequence[int], relevant_count: int, k: int) -> float:
    """Linear-gain nDCG. Ideal ranking places one evidence item per rank."""
    if k <= 0 or relevant_count <= 0:
        return 0.0
    dcg = 0.0
    for index, gain in enumerate(gains[:k]):
        if gain > 0:
            dcg += gain / math.log2(index + 2)
    ideal_hits = min(k, relevant_count)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    if idcg == 0.0:
        return 0.0
    return min(1.0, dcg / idcg)


def score_ranking(gains: Sequence[int], relevant_count: int) -> dict[str, float]:
    return {
        "hit@1": hit_at_k(gains, 1),
        "hit@3": hit_at_k(gains, 3),
        "hit@5": hit_at_k(gains, 5),
        "recall@5": recall_at_k(gains, relevant_count, 5),
        "mrr@10": mrr_at_k(gains, 10),
        "ndcg@10": ndcg_at_k(gains, relevant_count, 10),
    }


def gains_for_case(results: list[dict[str, Any]], case: dict[str, Any]) -> tuple[list[int], int]:
    """Label a ranked list with the case's evidence, else its expected sources."""
    evidence = case.get("expected_evidence") or []
    if evidence:
        return evidence_gains(results, evidence), len(evidence)
    sources = [str(source) for source in (case.get("expected_sources") or []) if source]
    return source_gains(results, sources), len(sources)


def mean_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {key: 0.0 for key in METRIC_KEYS}
    return {key: sum(row[key] for row in rows) / len(rows) for key in METRIC_KEYS}
