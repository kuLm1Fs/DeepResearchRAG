"""Unit tests for ablation ranking metrics.

Expectations are derived from the metric definitions, not from a retrieval run.
"""

import math

import pytest

from src.eval.metrics import evidence_gains, evidence_hit_at_k, source_gains
from src.eval.ranking import (
    gains_for_case,
    hit_at_k,
    mean_metrics,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    score_ranking,
)


def test_hit_mrr_recall_and_ndcg_follow_their_definitions():
    gains = [0, 1, 0, 1]

    assert hit_at_k(gains, 1) == 0.0
    assert hit_at_k(gains, 3) == 1.0
    assert hit_at_k([], 5) == 0.0
    assert mrr_at_k(gains, 10) == pytest.approx(1 / 2)
    assert mrr_at_k(gains, 1) == 0.0
    assert recall_at_k(gains, relevant_count=2, k=3) == pytest.approx(1 / 2)
    assert recall_at_k(gains, relevant_count=2, k=5) == pytest.approx(1.0)
    assert recall_at_k([1], relevant_count=0, k=5) == 0.0

    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(gains, relevant_count=2, k=10) == pytest.approx(min(1.0, dcg / idcg))
    assert ndcg_at_k([1, 1], relevant_count=2, k=10) == pytest.approx(1.0)
    assert ndcg_at_k([2], relevant_count=2, k=10) == 1.0
    assert ndcg_at_k([1], relevant_count=1, k=0) == 0.0


def test_score_ranking_exposes_the_ablation_cutoffs():
    scored = score_ranking([1, 0, 0], relevant_count=1)

    assert set(scored) == {"hit@1", "hit@3", "hit@5", "recall@5", "mrr@10", "ndcg@10"}
    assert scored["hit@1"] == 1.0
    assert scored["mrr@10"] == 1.0
    assert mean_metrics([scored, score_ranking([0], relevant_count=1)])["hit@1"] == pytest.approx(
        0.5
    )
    assert mean_metrics([])["hit@5"] == 0.0


def test_evidence_gains_match_evidence_hit_and_stack_on_one_chunk():
    results = [
        {
            "doc_name": "AAPL_2023_10K",
            "section": "consolidated statements",
            "content": "Net sales were $383,285 million in 2023. Total revenue was $211,915 million.",
        },
        {
            "doc_name": "MSFT_2023_10K",
            "content": "Ignored.",
        },
    ]
    expected = [
        {
            "source_id": "AAPL_2023_10K",
            "must_contain": ["Net sales", "383,285"],
            "section": "consolidated statements",
        },
        {
            "source_id": "AAPL_2023_10K",
            "must_contain": ["211,915"],
        },
    ]

    assert evidence_gains(results, expected) == [2, 0]
    assert evidence_hit_at_k(results, expected, 1) == pytest.approx(1.0)
    assert sum(evidence_gains(results[:1], expected)) / len(expected) == pytest.approx(
        evidence_hit_at_k(results, expected, 1)
    )


def test_gains_for_case_falls_back_to_expected_sources():
    results = [
        {"doc_name": "AAPL_2023_10K", "title": "Apple"},
        {"doc_name": "MSFT_2023_10K", "title": "Microsoft"},
    ]
    case = {"expected_sources": ["AAPL_2023_10K", "MSFT_2023_10K"]}

    gains, relevant_count = gains_for_case(results, case)

    assert gains == source_gains(results, case["expected_sources"])
    assert gains == [1, 1]
    assert relevant_count == 2
    assert recall_at_k(gains, relevant_count, 1) == pytest.approx(0.5)
