# Finance Eval Datasets

This directory stores retrieval and RAG quality datasets.

## Golden Set

Use JSON when the dataset is generated in batch:

```json
{
  "version": 3,
  "domain": "finance",
  "queries": [
    {
      "id": "fb-001",
      "query": "What was Apple's fiscal 2023 revenue?",
      "expected_sources": ["AAPL_2023_10K"],
      "expected_keywords": ["revenue", "fiscal 2023"],
      "gold_answer": "$383.3 billion",
      "difficulty": "easy",
      "category": "revenue"
    }
  ]
}
```

`build_financebench_eval.py` already emits `doc_name`; the loader treats that
as `expected_sources` when the field is missing.

## Badcases

Use JSONL for manually reviewed regressions. Each line is one case:

```jsonl
{"id":"bc-001","case_type":"badcase","query":"Compare Apple and Microsoft fiscal 2023 revenue","expected_sources":["AAPL_2023_10K","MSFT_2023_10K"],"failure_type":"missing_cross_source_evidence","expected_behavior":"retrieve both annual reports before answering","difficulty":"medium","category":"comparison"}
```

Badcases should come from user negative feedback or manual review, then be
curated before they become a gate.

## Running

```bash
PYTHONPATH=src python scripts/evaluate_retrieval.py --queries data/eval/badcases.jsonl
```

The retrieval gate checks:

- `Precision@5 >= 0.8`
- `Source Recall@5 >= 0.7` for cases with `expected_sources`
- `Badcase Fix Rate == 100%`
