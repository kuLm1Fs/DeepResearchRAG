"""Ablation runner with a fake retriever store. No live Milvus or embedding API."""

import json
from pathlib import Path

import pytest

from scripts import ablation as ablation_script
from scripts.ablation import NoRetrievalResults, build_parser, execute, run_ablation


class FakeStore:
    def __init__(self):
        self.search_calls = 0
        self.query_calls = 0

    async def search_async(self, **kwargs):
        self.search_calls += 1
        return [
            {
                "chunk_id": "financebench:ACME_2020_10K:p1:e0:0",
                "content_hash": "acme",
                "title": "ACME ACME_2020_10K page 1",
                "content": "Net sales 100",
                "source": "FinanceBench",
                "doc_name": "ACME_2020_10K",
                "score": 0.9,
                "published_at": 0,
            }
        ]

    async def query_async(self, expr, output_fields=None, limit=100):
        self.query_calls += 1
        if "content like" in expr:
            return [
                {
                    "chunk_id": "financebench:BETA_2021_10K:p2:e0:0",
                    "content_hash": "beta",
                    "title": "BETA_2021_10K page 2",
                    "content": "unrelated note",
                    "source": "FinanceBench",
                    "score": 0.5,
                    "published_at": 0,
                }
            ]
        return []


def _questions() -> dict:
    return {
        "queries": [
            {
                "id": "q1",
                "query": "What is ACME net sales?",
                "expected_sources": ["ACME_2020_10K"],
                "expected_evidence": [
                    {
                        "source_id": "ACME_2020_10K",
                        "chunk_id": "financebench:ACME_2020_10K:p1:e0:0",
                        "must_contain": ["Net sales"],
                    }
                ],
            },
            {
                "id": "q2",
                "query": "What is BETA margin?",
                "expected_sources": ["BETA_2021_10K"],
                "expected_evidence": [
                    {
                        "source_id": "BETA_2021_10K",
                        "must_contain": ["gross margin"],
                    }
                ],
            },
        ]
    }


def _identity_rerank(self, query, results, top_k):
    ranked = []
    for item in results:
        copied = dict(item)
        copied["rerank_score"] = float(copied.get("fused_score", copied.get("score", 0.0)) or 0.0)
        ranked.append(copied)
    return ranked[:top_k]


@pytest.fixture
def patched_io(monkeypatch):
    async def _embed(texts):
        return [[0.2, 0.3] for _ in texts]

    monkeypatch.setattr("retrieval.retriever.embed_texts_async", _embed)
    monkeypatch.setattr("retrieval.reranker.CrossEncoderReranker.rerank", _identity_rerank)


def _write_questions(path: Path) -> None:
    path.write_text(json.dumps(_questions()), encoding="utf-8")


@pytest.mark.asyncio
async def test_ablation_writes_table_and_reuses_path_cache(tmp_path, patched_io):
    questions = tmp_path / "questions.json"
    _write_questions(questions)
    output = tmp_path / "out"
    cache = tmp_path / "cache"
    store = FakeStore()
    args = build_parser().parse_args(
        [
            "--queries",
            str(questions),
            "--output",
            str(output),
            "--cache-dir",
            str(cache),
            "--limit",
            "1",
            "--configs",
            "vector,bm25,title,vector+bm25,vector+bm25+title,full",
        ]
    )

    code = await execute(args, store_factory=lambda: store)

    assert code == 0
    assert store.search_calls == 1
    runs = sorted(path for path in output.iterdir() if path.is_dir())
    assert len(runs) == 1
    payload = json.loads((runs[0] / "results.json").read_text(encoding="utf-8"))
    by_name = {row["name"]: row for row in payload["configs"]}
    assert payload["query_count"] == 1
    assert list(by_name) == [
        "vector",
        "bm25",
        "title",
        "vector_bm25",
        "vector_bm25_title",
        "full",
    ]
    assert by_name["vector"]["metrics"]["hit@1"] == 1.0
    assert by_name["bm25"]["metrics"]["hit@1"] == 0.0
    assert by_name["bm25"]["delta_vs_vector"]["hit@1"] == (
        by_name["bm25"]["metrics"]["hit@1"] - by_name["vector"]["metrics"]["hit@1"]
    )
    assert by_name["vector"]["delta_vs_vector"] is None
    assert by_name["full"]["rerank"] == "cross_encoder"
    assert "avg_latency_ms" in by_name["vector"]["metrics"]

    markdown = (runs[0] / "results.md").read_text(encoding="utf-8")
    csv_text = (runs[0] / "results.csv").read_text(encoding="utf-8")
    assert "vector only" in markdown
    assert "相对 vector only 的差值" in markdown
    assert (
        ablation_script._fmt_delta("hit@1", by_name["bm25"]["delta_vs_vector"]["hit@1"]) in markdown
    )
    assert "config,hit@1" in csv_text

    await execute(args, store_factory=lambda: store)
    assert store.search_calls == 1


@pytest.mark.asyncio
async def test_configs_subset_and_empty_retrieval_writes_nothing(tmp_path, patched_io):
    questions = tmp_path / "questions.json"
    _write_questions(questions)
    output = tmp_path / "out"
    store = FakeStore()
    args = build_parser().parse_args(
        [
            "--queries",
            str(questions),
            "--output",
            str(output),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--configs",
            "bm25,full",
            "--no-cache",
        ]
    )

    code = await execute(args, store_factory=lambda: store)
    payload = json.loads(next(output.glob("*/results.json")).read_text(encoding="utf-8"))

    assert code == 0
    assert payload["query_count"] == 2
    assert [row["name"] for row in payload["configs"]] == ["bm25", "full"]
    assert all(row["delta_vs_vector"] is None for row in payload["configs"])
    assert "本次没有跑 vector 配置" in next(output.glob("*/results.md")).read_text(encoding="utf-8")

    class EmptyStore:
        async def search_async(self, **kwargs):
            return []

        async def query_async(self, expr, output_fields=None, limit=100):
            return []

    empty_out = tmp_path / "empty"
    empty_args = build_parser().parse_args(
        [
            "--queries",
            str(questions),
            "--output",
            str(empty_out),
            "--no-cache",
            "--configs",
            "vector",
        ]
    )
    with pytest.raises(NoRetrievalResults):
        await execute(empty_args, store_factory=EmptyStore)
    assert not empty_out.exists()


@pytest.mark.asyncio
async def test_run_ablation_rejects_an_empty_case_list(patched_io):
    with pytest.raises(NoRetrievalResults):
        await run_ablation([], ["vector"], FakeStore(), None, dataset_label="none")
