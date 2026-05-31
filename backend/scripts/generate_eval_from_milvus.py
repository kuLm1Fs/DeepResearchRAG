#!/usr/bin/env python3
"""
Generate evaluation QA pairs from Milvus data using LLM.

Queries Milvus for finance-category documents, then uses DeepSeek to generate
question-answer pairs for evaluation.

Usage:
    PYTHONPATH=src python scripts/generate_eval_from_milvus.py
    PYTHONPATH=src python scripts/generate_eval_from_milvus.py --limit 50 --category finance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from core.config import settings
from llm import create_llm
from vectorstore import MilvusStore

configure_logging()
logger = get_logger(__name__)

GENERATE_PROMPT = """你是一个金融领域的评测集生成器。根据以下金融文档，生成 2 个问答对。

文档标题: {title}
文档来源: {source}
文档类别: {category}
文档内容: {content}

要求:
1. 第一个问题为 easy 难度（直接从文档中提取事实）
2. 第二个问题为 medium 难度（需要理解或简单推理）
3. 每个问题必须能从文档中找到答案
4. expected_keywords 列出文档中必然出现的关键词（用于检索命中判定）
5. gold_answer 给出标准答案（基于文档内容）
6. 如果文档是中文，问题用中文；如果是英文，问题用英文

输出 JSON 数组（不要加 markdown 代码块标记）:
[
  {{
    "query": "问题",
    "language": "zh 或 en",
    "expected_keywords": ["关键词1", "关键词2", "关键词3"],
    "gold_answer": "标准答案",
    "difficulty": "easy"
  }},
  {{
    "query": "问题",
    "language": "zh 或 en",
    "expected_keywords": ["关键词1", "关键词2", "关键词3"],
    "gold_answer": "标准答案",
    "difficulty": "medium"
  }}
]"""


def parse_llm_json(text: str) -> list[dict] | None:
    """Extract JSON array from LLM response, handling code blocks."""
    import re
    # Try direct parse
    try:
        data = json.loads(text.strip())
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        pass
    # Try extracting from code block
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    logger.warning("parse_failed", raw=text[:200])
    return None


async def generate_for_doc(
    llm: Any,
    doc: dict[str, Any],
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Generate 2 QA pairs for a single document."""
    async with sem:
        content = doc.get("content", "")[:2000]
        prompt = GENERATE_PROMPT.format(
            title=doc.get("title", ""),
            source=doc.get("source", ""),
            category=doc.get("category", ""),
            content=content,
        )
        try:
            result = await llm.chat([{"role": "user", "content": prompt}])
            pairs = parse_llm_json(result)
            if pairs:
                # Enrich with source metadata
                for p in pairs:
                    p["source_doc"] = doc.get("title", "")[:100]
                    p["source_category"] = doc.get("category", "")
                return pairs
        except Exception as e:
            logger.error("generate_failed", doc=doc.get("title", "")[:50], error=str(e))
    return []


async def main_async(args: argparse.Namespace) -> int:
    store = MilvusStore()
    llm = create_llm(
        provider=settings.llm_provider,
        api_key=settings.deepseek_api_key,
        model=settings.llm_model,
    )

    # Query Milvus for finance docs
    expr = f'category == "{args.category}"' if args.category else None
    results = store.query(expr=expr, limit=args.limit or 200, output_fields=[
        "title", "content", "source", "category", "language", "parent_doc_id",
    ])
    logger.info("docs_found", count=len(results))

    if not results:
        print(f"No documents found for category={args.category}")
        return 1

    # Deduplicate by parent_doc_id, take top N
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        pid = r.get("parent_doc_id", r.get("title", ""))
        by_parent[pid].append(r)

    docs = []
    for pid, chunks in list(by_parent.items())[: args.limit or 50]:
        # Pick the longest chunk as representative
        best = max(chunks, key=lambda c: len(c.get("content", "")))
        docs.append(best)

    print(f"Generating QA pairs for {len(docs)} documents...")

    sem = asyncio.Semaphore(args.concurrency or 5)
    tasks = [generate_for_doc(llm, doc, sem) for doc in docs]
    results_nested = await asyncio.gather(*tasks)

    all_pairs = []
    for pairs in results_nested:
        all_pairs.extend(pairs)

    # Add IDs
    for i, pair in enumerate(all_pairs):
        pair["id"] = f"auto-{i + 1:03d}"

    # Write output
    output_path = Path(args.output) if args.output else Path(__file__).parent.parent / "data" / "eval_finance_auto.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dataset = {
        "version": 2,
        "domain": "finance",
        "source": "LLM-generated from Milvus",
        "description": f"Auto-generated QA pairs from {args.category or 'all'} category documents",
        "queries": all_pairs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    difficulties = {}
    for p in all_pairs:
        d = p.get("difficulty", "unknown")
        difficulties[d] = difficulties.get(d, 0) + 1

    print(f"\nGenerated {len(all_pairs)} QA pairs from {len(docs)} documents")
    print(f"  Difficulty: {difficulties}")
    print(f"  Output: {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate eval QA from Milvus data")
    parser.add_argument("--limit", type=int, default=50, help="Max documents to process")
    parser.add_argument("--category", type=str, default="finance", help="Milvus category filter")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent LLM calls")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
