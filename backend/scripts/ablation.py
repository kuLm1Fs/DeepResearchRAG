#!/usr/bin/env python3
"""Run a FinanceBench retrieval ablation.

From backend/:

    PYTHONPATH=src python scripts/ablation.py
    PYTHONPATH=src python scripts/ablation.py --limit 5
    PYTHONPATH=src python scripts/ablation.py --configs vector,bm25,full

The script writes a markdown table, JSON, and CSV under
data/eval_results/ablation/<timestamp>/. It does not write a results file
when every configuration returns zero documents.

``bm25`` selects the existing keyword/fulltext path (Milvus LIKE on title
and content). Latency for a configuration is the max of its enabled path
latencies, plus fusion/rerank time. Cached paths reuse the latency measured
the first time that path ran.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.datasets import load_eval_cases
from eval.ranking import METRIC_KEYS, gains_for_case, mean_metrics, score_ranking
from retrieval.cache import RetrievalPathCache
from retrieval.components import ABLATION_LABELS, ABLATION_PRESETS, parse_ablation_configs
from retrieval.retriever import MultiPathRetriever

RATE_KEYS = METRIC_KEYS
LATENCY_KEY = "avg_latency_ms"
DISPLAY_KEYS = RATE_KEYS + (LATENCY_KEY,)
BASELINE = "vector"
RETRIEVE_K = 10


class NoRetrievalResults(RuntimeError):
    """Raised when Milvus/embedding produced no documents to score."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FinanceBench retrieval ablation")
    parser.add_argument(
        "--queries",
        type=str,
        default=None,
        help="Eval JSON/JSONL. Default: data/eval_financebench.json",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Directory for a timestamped run folder. Default: data/eval_results/ablation",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Per-path retrieval cache. Default: data/eval_results/ablation_cache",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Evaluate only the first N questions"
    )
    parser.add_argument(
        "--configs",
        type=str,
        default=None,
        help="Comma-separated configs. Default: vector,bm25,title,vector_bm25,vector_bm25_title,full",
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Do not read or write the path cache"
    )
    return parser


def resolve_backend_path(path: str | None, default: Path) -> Path:
    if path is None:
        return default
    given = Path(path)
    return given if given.is_absolute() else Path(__file__).resolve().parent.parent / given


def _rerank_mode(components_reranker: bool, batches: list[list[dict[str, Any]]]) -> str:
    if not components_reranker:
        return "off"
    saw_fallback = False
    saw_scores = False
    for results in batches:
        for item in results:
            if item.get("rerank_mode") == "lexical_fallback":
                saw_fallback = True
            elif "rerank_score" in item:
                saw_scores = True
    if saw_fallback and saw_scores:
        return "mixed"
    if saw_fallback:
        return "lexical_fallback"
    if saw_scores:
        return "cross_encoder"
    return "unobserved"


def _delta(metrics: dict[str, float], baseline: dict[str, float]) -> dict[str, float]:
    return {key: metrics[key] - baseline[key] for key in DISPLAY_KEYS}


async def run_ablation(
    cases: list[dict[str, Any]],
    config_names: list[str],
    store: Any,
    cache: RetrievalPathCache | None,
    dataset_label: str,
) -> dict[str, Any]:
    """Score each config. Returns the report payload and does not write files."""
    if not cases:
        raise NoRetrievalResults("没有可评测的问题。")

    config_rows: list[dict[str, Any]] = []
    total_retrieved = 0

    for name in config_names:
        components = ABLATION_PRESETS[name]
        retriever = MultiPathRetriever(
            store,
            components=components,
            path_cache=cache,
            graph_retriever=None,
        )
        per_query: list[dict[str, Any]] = []
        batches: list[list[dict[str, Any]]] = []
        retrieved = 0

        for case in cases:
            results = await retriever.retrieve(case["query"], top_k=RETRIEVE_K)
            batches.append(results)
            retrieved += len(results)
            gains, relevant_count = gains_for_case(results, case)
            scored = score_ranking(gains, relevant_count)
            per_query.append(
                {
                    "id": case.get("id", ""),
                    "latency_ms": retriever.last_retrieval_latency_ms,
                    **scored,
                }
            )

        total_retrieved += retrieved
        metric_rows = [{key: row[key] for key in METRIC_KEYS} for row in per_query]
        metrics = mean_metrics(metric_rows)
        latencies = [float(row["latency_ms"]) for row in per_query]
        metrics[LATENCY_KEY] = sum(latencies) / len(latencies) if latencies else 0.0
        config_rows.append(
            {
                "name": name,
                "label": ABLATION_LABELS[name],
                "components": components.as_dict(),
                "rerank": _rerank_mode(components.reranker, batches),
                "retrieved_documents": retrieved,
                "metrics": metrics,
                "queries": per_query,
            }
        )

    if total_retrieved == 0:
        raise NoRetrievalResults(
            "所有配置的检索结果都是空的。请确认 Milvus 已启动、FinanceBench 已入库、"
            "并且向量路径所需的 VOLCENGINE_API_KEY 可用。未写入结果文件。"
        )

    baseline_metrics = next(
        (row["metrics"] for row in config_rows if row["name"] == BASELINE),
        None,
    )
    for row in config_rows:
        if baseline_metrics is None or row["name"] == BASELINE:
            row["delta_vs_vector"] = None
        else:
            row["delta_vs_vector"] = _delta(row["metrics"], baseline_metrics)

    return {
        "dataset": dataset_label,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "query_count": len(cases),
        "top_k": RETRIEVE_K,
        "baseline": BASELINE,
        "notes": [
            "bm25 是现有关键词全文路径（Milvus 对 title/content 的 LIKE 查询），不是单独的 BM25 打分器。",
            "full 含三路召回、RRF、时间衰减、来源加权和 reranker，不含 Neo4j 图检索。",
            "平均延迟 = 启用路径首次实测耗时的最大值 + 本次融合/重排耗时。缓存命中沿用首次实测，不把读盘算进去。",
            "Hit/MRR/nDCG/Recall 使用评测集的 expected_evidence；没有证据标注时退回 expected_sources。",
            "rerank 为 lexical_fallback 时，CrossEncoder 权重不可用，走了现有词面兜底。",
        ],
        "configs": config_rows,
    }


def _fmt_rate(value: float) -> str:
    return f"{value:.4f}"


def _fmt_ms(value: float) -> str:
    return f"{value:.1f}"


def _fmt_metric(key: str, value: float) -> str:
    if key == LATENCY_KEY:
        return _fmt_ms(value)
    return _fmt_rate(value)


def _fmt_delta(key: str, value: float) -> str:
    if key == LATENCY_KEY:
        return f"{value:+.1f}"
    return f"{value:+.4f}"


def render_markdown(payload: dict[str, Any]) -> str:
    headers = [
        "config",
        "Hit@1",
        "Hit@3",
        "Hit@5",
        "Recall@5",
        "MRR@10",
        "nDCG@10",
        "avg latency (ms)",
    ]
    lines = [
        "# FinanceBench retrieval ablation",
        "",
        f"- 数据集: `{payload['dataset']}`",
        f"- 问题数: {payload['query_count']}",
        f"- 每题返回条数: {payload['top_k']}",
        "",
        "Hit@K 表示前 K 条里是否至少命中一条标注证据。Recall@5 是前 5 条覆盖的证据条数占该题证据条数的比例。MRR@10 是首条命中的倒数排名（10 名以外记 0）。nDCG@10 用证据条数作为增益。最后一列是平均检索延迟（毫秒）。",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |",
    ]
    for row in payload["configs"]:
        metrics = row["metrics"]
        cells = [row["label"]] + [_fmt_metric(key, metrics[key]) for key in DISPLAY_KEYS]
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## 相对 vector only 的差值", ""])
    if not any(row["name"] == BASELINE for row in payload["configs"]):
        lines.append("本次没有跑 vector 配置，所以没有差值。")
    else:
        lines.append("每个数都是该配置减去 vector only。延迟差为正表示更慢。")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] + ["---:"] * (len(headers) - 1)) + " |")
        for row in payload["configs"]:
            delta = row["delta_vs_vector"]
            if delta is None:
                cells = [row["label"]] + ["—"] * len(DISPLAY_KEYS)
            else:
                cells = [row["label"]] + [_fmt_delta(key, delta[key]) for key in DISPLAY_KEYS]
            lines.append("| " + " | ".join(cells) + " |")

    lines.extend(["", "## 配置说明", ""])
    for row in payload["configs"]:
        lines.append(
            f"- `{row['name']}` {row['label']}: 取回 {row['retrieved_documents']} 条文档，rerank={row['rerank']}。"
        )
    lines.extend(["", "## 读表时要注意", ""])
    for note in payload["notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_reports(payload: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "results.json"
    csv_path = output_dir / "results.csv"
    md_path = output_dir / "results.md"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(payload), encoding="utf-8")

    fieldnames = ["config", *DISPLAY_KEYS]
    delta_fields = [f"delta_{key}" for key in DISPLAY_KEYS]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames + delta_fields)
        writer.writeheader()
        for row in payload["configs"]:
            record: dict[str, Any] = {"config": row["name"]}
            for key in DISPLAY_KEYS:
                record[key] = row["metrics"][key]
            delta = row["delta_vs_vector"] or {}
            for key in DISPLAY_KEYS:
                record[f"delta_{key}"] = "" if row["delta_vs_vector"] is None else delta[key]
            writer.writerow(record)

    return {"json": json_path, "csv": csv_path, "markdown": md_path}


def _load_cases(path: Path, limit: int | None) -> list[dict[str, Any]]:
    cases = load_eval_cases(path)
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit 必须是正整数")
        cases = cases[:limit]
    return cases


async def execute(args: argparse.Namespace, store_factory: Any = None) -> int:
    backend_dir = Path(__file__).resolve().parent.parent
    query_path = resolve_backend_path(args.queries, backend_dir / "data" / "eval_financebench.json")
    output_root = resolve_backend_path(
        args.output, backend_dir / "data" / "eval_results" / "ablation"
    )
    cache_dir = resolve_backend_path(
        args.cache_dir,
        backend_dir / "data" / "eval_results" / "ablation_cache",
    )
    config_names = parse_ablation_configs(args.configs)
    cases = _load_cases(query_path, args.limit)
    cache = None if args.no_cache else RetrievalPathCache(cache_dir)
    factory = store_factory or _default_store_factory
    store = factory()

    payload = await run_ablation(
        cases,
        config_names,
        store,
        cache,
        dataset_label=str(query_path),
    )
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    written = write_reports(payload, output_root / stamp)
    print(render_markdown(payload))
    print(f"JSON: {written['json']}")
    print(f"CSV:  {written['csv']}")
    print(f"MD:   {written['markdown']}")
    return 0


def _default_store_factory() -> Any:
    from vectorstore import MilvusStore

    return MilvusStore()


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(execute(args))
    except NoRetrievalResults as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"检索消融失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
