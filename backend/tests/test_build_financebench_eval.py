from scripts.build_financebench_eval import build_eval_queries
from scripts.build_financebench_eval import extract_evidence_terms


def test_extract_evidence_terms_ignores_single_digit_company_name_fragments():
    terms = extract_evidence_terms(
        "3M reported net income attributable to 3M of $5,349 million in 2018."
    )

    assert terms == ["5,349", "2018", "net income"]


def test_build_eval_queries_outputs_v3_evidence_specs():
    questions = [
        {
            "doc_name": "AAPL_2023_10K",
            "company": "Apple",
            "question": "What was Apple's net sales in fiscal 2023?",
            "answer": "$383.285 billion",
            "question_type": "metrics-generated",
            "evidence": [
                {
                    "evidence_page_num": 42,
                    "evidence_text": (
                        "Net sales were $383,285 million during 2023, compared to "
                        "$394,328 million during 2022."
                    ),
                }
            ],
        }
    ]
    meta = [{"doc_name": "AAPL_2023_10K", "doc_type": "10-K"}]

    queries = build_eval_queries(questions, meta, limit=None)

    assert queries[0]["query_type"] == "single_source_fact"
    assert queries[0]["expected_sources"] == ["AAPL_2023_10K"]
    assert queries[0]["required_sources"] == ["AAPL_2023_10K"]
    assert queries[0]["expected_evidence"] == [
        {
            "source_id": "AAPL_2023_10K",
            "chunk_id": "financebench:AAPL_2023_10K:p42:e0:0",
            "page": 42,
            "must_contain": ["383,285", "2023", "net sales"],
        }
    ]
    assert queries[0]["evidence_texts"] == [
        "Net sales were $383,285 million during 2023, compared to $394,328 million during 2022."
    ]
