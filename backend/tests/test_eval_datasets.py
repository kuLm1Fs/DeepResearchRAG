import json

import pytest

from eval.datasets import load_eval_cases, split_eval_cases


def test_load_eval_cases_accepts_versioned_json_dataset(tmp_path):
    dataset = {
        "version": 3,
        "domain": "finance",
        "queries": [
            {
                "id": "fb-001",
                "query": "What was Apple's revenue?",
                "query_type": "numeric_fact",
                "expected_sources": ["AAPL_2023_10K"],
                "required_sources": ["AAPL_2023_10K"],
                "expected_evidence": [
                    {
                        "source_id": "AAPL_2023_10K",
                        "must_contain": ["Net sales", "2023", "383,285"],
                        "section": "consolidated statements",
                    }
                ],
                "expected_numbers": [
                    {"value": 383.3, "unit": "billion USD", "period": "fiscal 2023"}
                ],
                "temporal_constraints": {"fiscal_year": "2023"},
                "gold_answer": "$383.3 billion",
                "difficulty": "easy",
                "category": "revenue",
            }
        ],
    }
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    cases = load_eval_cases(path)

    assert cases == [
        {
            "id": "fb-001",
            "query": "What was Apple's revenue?",
            "query_type": "numeric_fact",
            "expected_sources": ["AAPL_2023_10K"],
            "required_sources": ["AAPL_2023_10K"],
            "expected_evidence": [
                {
                    "source_id": "AAPL_2023_10K",
                    "must_contain": ["Net sales", "2023", "383,285"],
                    "section": "consolidated statements",
                }
            ],
            "expected_numbers": [
                {"value": 383.3, "unit": "billion USD", "period": "fiscal 2023"}
            ],
            "temporal_constraints": {"fiscal_year": "2023"},
            "expected_keywords": [],
            "gold_answer": "$383.3 billion",
            "difficulty": "easy",
            "category": "revenue",
            "case_type": "golden",
            "failure_type": "",
            "expected_behavior": "",
        }
    ]


def test_load_eval_cases_defaults_finance_extensions(tmp_path):
    dataset = [{"query": "What was Apple's revenue?"}]
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    cases = load_eval_cases(path)

    assert cases[0]["query_type"] == "general"
    assert cases[0]["required_sources"] == []
    assert cases[0]["expected_evidence"] == []
    assert cases[0]["expected_numbers"] == []
    assert cases[0]["temporal_constraints"] == {}


def test_load_eval_cases_uses_doc_name_as_expected_source_for_financebench(tmp_path):
    dataset = {
        "queries": [
            {
                "id": "fb-002",
                "query": "What was Microsoft's operating income?",
                "doc_name": "MSFT_2023_10K",
                "expected_keywords": ["operating income"],
            }
        ]
    }
    path = tmp_path / "financebench.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    cases = load_eval_cases(path)

    assert cases[0]["expected_sources"] == ["MSFT_2023_10K"]


def test_load_eval_cases_accepts_jsonl_badcases_and_defaults_case_type(tmp_path):
    path = tmp_path / "badcases.jsonl"
    path.write_text(
        json.dumps(
            {
                "query": "Compare NVIDIA and TSMC gross margin",
                "expected_sources": ["NVDA_2024_10K", "TSM_2024_20F"],
                "failure_type": "missing_cross_source_evidence",
                "expected_behavior": "retrieve both filings before answering",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_eval_cases(path)
    golden, badcases = split_eval_cases(cases)

    assert golden == []
    assert badcases[0]["case_type"] == "badcase"
    assert badcases[0]["id"] == "case-001"
    assert badcases[0]["expected_behavior"] == "retrieve both filings before answering"


def test_load_eval_cases_reports_invalid_line_number_for_jsonl(tmp_path):
    path = tmp_path / "badcases.jsonl"
    path.write_text('{"query": "ok"}\n{"bad": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="badcases.jsonl:2 missing required field: query"):
        load_eval_cases(path)
