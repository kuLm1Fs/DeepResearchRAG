from scripts.seed_financebench import BATCH_SIZE, build_records


def test_financebench_seed_uses_embedding_api_batch_limit():
    assert BATCH_SIZE <= 16


def test_build_records_maps_financebench_evidence_for_vector_and_graph_ingestion():
    questions = [
        {
            "doc_name": "AAPL_2023_10K",
            "company": "Apple",
            "question": "What was Apple's net sales in fiscal 2023?",
            "evidence": [
                {
                    "evidence_page_num": 42,
                    "evidence_text": "Net sales were 383,285 million in 2023.",
                    "evidence_text_full_page": "Net sales were 383,285 million in 2023. " * 3,
                }
            ],
        }
    ]
    meta = [
        {
            "doc_name": "AAPL_2023_10K",
            "doc_type": "10-K",
            "doc_link": "https://example.com/aapl-10k",
        }
    ]

    records = build_records(questions, meta, limit=None)

    assert len(records) == 1
    record = records[0]
    assert record["source"] == "FinanceBench"
    assert record["category"] == "10-K"
    assert record["parent_doc_id"] == "AAPL_2023_10K"
    assert record["external_id"] == "financebench:AAPL_2023_10K:p42:e0"
    assert record["url"] == "https://example.com/aapl-10k"
    assert record["content_hash"]
    assert "383,285" in record["content"]
