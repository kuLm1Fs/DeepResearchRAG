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
      "query_type": "numeric_fact",
      "expected_sources": ["AAPL_2023_10K"],
      "required_sources": ["AAPL_2023_10K"],
      "expected_evidence": [
        {
          "source_id": "AAPL_2023_10K",
          "must_contain": ["Net sales", "2023", "383,285"],
          "section": "consolidated statements"
        }
      ],
      "expected_numbers": [
        {"value": 383.3, "unit": "billion USD", "period": "fiscal 2023"}
      ],
      "temporal_constraints": {"fiscal_year": "2023"},
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

Recommended `query_type` values:

- `single_source_fact`: one source should answer the question.
- `numeric_fact`: answer depends on a specific value, unit, and period.
- `comparison`: multiple required sources must be retrieved.
- `temporal`: answer depends on a date or fiscal period constraint.
- `general`: fallback for smoke tests or broad questions.

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
- `Required Source Coverage@5 >= 0.85` for cases with `required_sources`
- `Evidence Hit@5 >= 0.75` for cases with `expected_evidence`
- `Badcase Fix Rate == 100%`

The end-to-end gate also reports `Numeric Accuracy` for cases with
`expected_numbers`, alongside faithfulness, relevance, correctness, and
citation coverage.
