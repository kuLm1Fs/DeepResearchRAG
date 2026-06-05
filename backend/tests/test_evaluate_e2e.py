import pytest

from scripts import evaluate_e2e as eval_script


class FakeRetriever:
    async def retrieve(self, query, top_k):
        return [
            {
                "doc_name": "AAPL_2023_10K",
                "content": "Net sales were $383.3 billion USD in fiscal 2023.",
            }
        ]


class FakeJudge:
    async def judge_faithfulness(self, query, answer, sources):
        return {"score": 5, "reasoning": "grounded"}

    async def judge_relevance(self, query, answer):
        return {"score": 5, "reasoning": "answers the question"}

    async def judge_correctness(self, query, answer, gold_answer):
        return {"score": 5, "reasoning": "matches gold"}


@pytest.mark.asyncio
async def test_evaluate_single_reports_numeric_accuracy(monkeypatch):
    async def fake_generate_answer_only(query, retrieval_results):
        return (
            "Apple fiscal 2023 revenue was $383.3 billion USD.",
            retrieval_results,
            [{"support_level": "supported"}],
        )

    monkeypatch.setattr(eval_script, "generate_answer_only", fake_generate_answer_only)

    result = await eval_script.evaluate_single(
        {
            "id": "fb-001",
            "query": "What was Apple's fiscal 2023 revenue?",
            "expected_keywords": ["revenue"],
            "expected_numbers": [
                {"value": 383.3, "unit": "billion USD", "period": "fiscal 2023"}
            ],
            "gold_answer": "$383.3 billion",
            "query_type": "numeric_fact",
        },
        FakeRetriever(),
        FakeJudge(),
    )

    assert result["answer"]["numeric_accuracy"] == 1.0
    assert result["query_type"] == "numeric_fact"


@pytest.mark.asyncio
async def test_run_evaluation_aggregates_numeric_accuracy(monkeypatch):
    async def fake_evaluate_single(query_item, retriever, judge):
        return {
            "query_id": query_item["id"],
            "query": query_item["query"],
            "query_type": query_item["query_type"],
            "difficulty": "easy",
            "retrieval": {"keyword_hit_rate": 1.0, "latency_ms": 10},
            "generation": {"latency_ms": 20},
            "citations": {"coverage_rate": 1.0, "supported": 1},
            "judge": {
                "faithfulness": {"score": 5},
                "relevance": {"score": 5},
                "latency_ms": 30,
            },
            "answer": {"numeric_accuracy": query_item["numeric_accuracy"]},
            "total_latency_ms": 60,
        }

    monkeypatch.setattr(eval_script, "evaluate_single", fake_evaluate_single)
    monkeypatch.setattr(eval_script, "MilvusStore", lambda: object())
    monkeypatch.setattr(eval_script, "MultiPathRetriever", lambda store: object())
    monkeypatch.setattr(eval_script, "EvalJudge", lambda: object())

    results = await eval_script.run_evaluation(
        [
            {
                "id": "q1",
                "query": "Apple revenue",
                "query_type": "numeric_fact",
                "numeric_accuracy": 1.0,
            },
            {
                "id": "q2",
                "query": "Microsoft revenue",
                "query_type": "numeric_fact",
                "numeric_accuracy": 0.0,
            },
        ]
    )

    assert results["summary"]["answer"]["avg_numeric_accuracy"] == 0.5
    assert results["summary"]["answer"]["numeric_accuracy_by_query_type"]["numeric_fact"] == 0.5
