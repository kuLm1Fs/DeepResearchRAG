#!/usr/bin/env python3
"""
Evaluate retrieval quality using test query set.

用法:
    python evaluate_retrieval.py [--queries data/eval_queries.json] [--output data/eval_results/]

参数:
    --queries: 测试查询集 JSON 文件路径
    --output: 输出目录路径
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 添加 src 到路径以便导入
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger, settings
from vectorstore import MilvusStore
from retrieval import MultiPathRetriever

# 配置日志
configure_logging()
logger = get_logger(__name__)

# 默认测试查询（备用）
DEFAULT_TEST_QUERIES = [
    {"query": "latest AI developments", "expected_categories": ["Sci/Tech"]},
    {"query": "cybersecurity breach news", "expected_categories": ["Sci/Tech"]},
    {"query": "科技创业融资", "expected_categories": ["Business"]},
    {"query": "football world cup results", "expected_categories": ["Sports"]},
    {"query": "stock market today", "expected_categories": ["Business"]},
    {"query": "international politics", "expected_categories": ["World"]},
    {"query": "新技术发布", "expected_categories": ["Sci/Tech"]},
    {"query": "篮球比赛结果", "expected_categories": ["Sports"]},
    {"query": "business company earnings", "expected_categories": ["Business"]},
    {"query": "science discoveries", "expected_categories": ["Sci/Tech"]},
]


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """
    计算 Precision@K

    Args:
        retrieved: 检索到的分类列表
        relevant: 期望的分类列表
        k: 取前 K 个结果

    Returns:
        Precision@K 值
    """
    if k == 0:
        return 0.0
    retrieved_k = retrieved[:k]
    return len([r for r in retrieved_k if r in relevant]) / k


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """
    计算 Recall@K

    Args:
        retrieved: 检索到的分类列表
        relevant: 期望的分类列表
        k: 取前 K 个结果

    Returns:
        Recall@K 值
    """
    if not relevant:
        return 0.0
    retrieved_k = retrieved[:k]
    return len([r for r in retrieved_k if r in relevant]) / len(relevant)


def load_test_queries(file_path: Path) -> list[dict]:
    """
    从 JSON 文件加载测试查询集

    Args:
        file_path: JSON 文件路径

    Returns:
        测试查询列表
    """
    if not file_path.exists():
        logger.warning("query_file_not_found", path=str(file_path), using_default=True)
        return DEFAULT_TEST_QUERIES

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            queries = json.load(f)
        logger.info("test_queries_loaded", count=len(queries), path=str(file_path))
        return queries
    except Exception as e:
        logger.error("query_file_load_failed", path=str(file_path), error=str(e))
        return DEFAULT_TEST_QUERIES


def main():
    """主函数：执行检索评估"""
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality")
    parser.add_argument("--queries", type=str, default="data/eval_queries.json",
                        help="Path to test queries JSON file")
    parser.add_argument("--output", type=str, default=None,
                        help="Output directory for results")
    args = parser.parse_args()

    # 解析路径
    script_dir = Path(__file__).parent.parent
    query_file = script_dir / args.queries
    output_dir = Path(args.output) if args.output else script_dir / "data" / "eval_results"

    logger.info("evaluation_started", query_file=str(query_file), output_dir=str(output_dir))

    # 加载测试查询
    test_queries = load_test_queries(query_file)

    # 初始化 Milvus store 和 retriever
    try:
        store = MilvusStore()
        retriever = MultiPathRetriever(store)
    except Exception as e:
        logger.error("milvus_connection_failed", error=str(e))
        print(f"错误: 无法连接 Milvus: {e}")
        sys.exit(1)

    # 执行评估
    results = []
    for item in test_queries:
        query = item.get("query", "")
        expected = item.get("expected_categories", [])

        try:
            retrieved = retriever.retrieve(query, top_k=5)
            retrieved_categories = [r.get("category", "") for r in retrieved]

            p5 = precision_at_k(retrieved_categories, expected, 5)
            r5 = recall_at_k(retrieved_categories, expected, 5)

            result = {
                "query": query,
                "expected": expected,
                "retrieved": retrieved_categories,
                "precision@5": round(p5, 3),
                "recall@5": round(r5, 3),
            }
            results.append(result)

            logger.info("query_evaluated",
                query=query[:50],
                precision=p5,
                recall=r5,
                retrieved=retrieved_categories,
            )

        except Exception as e:
            logger.error("query_eval_failed", query=query, error=str(e))
            results.append({
                "query": query,
                "expected": expected,
                "retrieved": [],
                "precision@5": 0.0,
                "recall@5": 0.0,
                "error": str(e),
            })

    # 计算平均值
    avg_precision = sum(r["precision@5"] for r in results) / len(results) if results else 0
    avg_recall = sum(r["recall@5"] for r in results) / len(results) if results else 0

    logger.info("evaluation_completed",
        avg_precision=avg_precision,
        avg_recall=avg_recall,
        total_queries=len(results),
    )

    # 保存结果
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{timestamp}.json"

    output_data = {
        "timestamp": timestamp,
        "total_queries": len(results),
        "avg_precision@5": round(avg_precision, 3),
        "avg_recall@5": round(avg_recall, 3),
        "target_precision": 0.8,
        "passed": avg_precision >= 0.8,
        "results": results,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # 打印摘要
    print(f"\n{'='*50}")
    print(f"检索评估结果")
    print(f"{'='*50}")
    print(f"测试查询数: {len(results)}")
    print(f"平均 Precision@5: {avg_precision:.3f}")
    print(f"平均 Recall@5: {avg_recall:.3f}")
    print(f"目标: >= 0.8")
    print(f"结果: {'✓ 通过' if avg_precision >= 0.8 else '✗ 未通过'}")
    print(f"\n详细结果已保存至: {output_file}")

    return 0 if avg_precision >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())