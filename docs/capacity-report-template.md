# Capacity Report Template

## Test Scope

- Target: RAG Finance Intelligence backend
- Date:
- Commit:
- Environment:
- Workers:
- CPU / memory:
- Dataset size:
- Fault scenario: none | `graph:timeout` | `llm:timeout` | `milvus:down` | `worker:slow`

## Load Profile

| Scenario | Weight | Target RPS | Duration | Notes |
|---|---:|---:|---:|---|
| `/api/query` non-stream | 6 | | | normal Q&A |
| `/api/query` SSE | 3 | | | source event + token stream |
| `/api/research` enqueue | 1 | | | long task admission only |

## SLO

| Metric | Budget |
|---|---:|
| Error rate | <= 1% |
| `/api/query` p95 | <= 2000 ms |
| `/api/query` p99 | <= 5000 ms |
| Research enqueue p95 | <= 500 ms |
| Dead letter growth | 0 during normal test |

## Result Summary

| Route | Requests | RPS | P50 | P95 | P99 | Error Rate | Bottlenecks |
|---|---:|---:|---:|---:|---:|---:|---|
| | | | | | | | |

## Degradation Evidence

| Component | Fault | Expected Policy | Observed Result | Pass |
|---|---|---|---|---|
| Graph | timeout/down | fallback to vector retrieval | | |
| LLM | timeout/429 | fail fast or evidence-only fallback | | |
| Milvus | down | fail request, do not fake answer | | |
| Worker | killed/slow | task heartbeat expires, retry or dead letter | | |

## Capacity Judgment

- First bottleneck:
- Saturation signal:
- User-visible behavior:
- Safe production limit:
- Next scaling action:

## Commands

```bash
cd backend
FAULT_SCENARIO=graph:timeout locust -f loadtests/locustfile.py --host http://localhost:8000
python scripts/generate_capacity_report.py data/locust-summary.json --output data/capacity_report.md
```
