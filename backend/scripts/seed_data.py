#!/usr/bin/env python3
"""
Seed data from HuggingFace ag_news dataset into Milvus.

用法:
    python seed_data.py [--limit 10000]

参数:
    --limit: 限制加载的样本数量，默认 10000
"""

import argparse
import sys
from pathlib import Path

# 添加 src 到路径以便导入
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datasets import load_dataset
from tqdm import tqdm

from core import configure_logging, get_logger, settings
from vectorstore import MilvusStore
from vectorstore.embedding import embed_texts

# 配置日志
configure_logging()
logger = get_logger(__name__)


def main():
    """主函数：加载 ag_news 数据集并写入 Milvus"""
    parser = argparse.ArgumentParser(description="Seed ag_news data into Milvus")
    parser.add_argument("--limit", type=int, default=10000, help="Number of articles to load")
    args = parser.parse_args()

    logger.info("seeding_data_started", limit=args.limit)

    try:
        # 初始化 Milvus store
        store = MilvusStore()
        store.create_collection(drop_existing=True)
        logger.info("milvus_collection_ready")

        # 加载数据集
        logger.info("loading_dataset", dataset="fancyzhx/ag_news")
        dataset = load_dataset("fancyzhx/ag_news", split=f"train[:{args.limit}]")
        logger.info("dataset_loaded", count=len(dataset))

        # 批量处理并插入
        batch_size = 50
        total_batches = (len(dataset) + batch_size - 1) // batch_size

        for i in tqdm(range(0, len(dataset), batch_size), desc="Seeding batches", unit="batch"):
            batch = dataset[i:i+batch_size]
            texts = [f"{item['title']} - {item['description']}" for item in batch]

            try:
                # 获取 embeddings
                embeddings = embed_texts(texts)

                # 准备记录
                records = []
                for item, embedding in zip(batch, embeddings):
                    records.append({
                        "title": item["title"],
                        "content": item["description"],
                        "source": "ag_news",
                        "language": "en",
                        "category": ["World", "Sports", "Business", "Sci/Tech"][item["label"]],
                        "published_at": 0,
                        "content_hash": "",
                        "embedding": embedding,
                    })

                store.insert(records)
                logger.debug("batch_inserted", batch=i//batch_size + 1, count=len(records))

            except Exception as e:
                logger.error("batch_insert_failed", batch=i//batch_size + 1, error=str(e))
                continue

        # 输出最终统计
        total = store.count()
        logger.info("seeding_completed", total=total)
        print(f"\n数据导入完成: {total} 条记录")

    except Exception as e:
        logger.error("seeding_failed", error=str(e))
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()