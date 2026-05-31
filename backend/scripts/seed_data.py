#!/usr/bin/env python3
"""
Seed data from HuggingFace ag_news dataset into Milvus.

用法:
    python seed_data.py [--limit 10000] [--chunk-size 500] [--user-id xxx] [--company-id xxx]

参数:
    --limit: 限制加载的样本数量，默认 10000
    --chunk-size: 文本分块大小，默认 500
    --user-id: 租户隔离的用户 ID
    --company-id: 租户隔离的公司 ID
"""

import argparse
import hashlib
import sys
import uuid
from pathlib import Path

# 添加 src 到路径以便导入
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datasets import load_dataset
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tqdm import tqdm

from core import configure_logging, get_logger, settings
from vectorstore import MilvusStore
from vectorstore.embedding import embed_texts

# 配置日志
configure_logging()
logger = get_logger(__name__)


def chunk_article(text: str, title: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """将一篇文章拆分为多个 chunk，返回 chunk 元数据列表。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )
    chunks = splitter.split_text(text)
    parent_doc_id = uuid.uuid4().hex[:16]

    result = []
    for idx, chunk_text in enumerate(chunks):
        result.append({
            "parent_doc_id": parent_doc_id,
            "chunk_id": f"{parent_doc_id}_{idx}",
            "title": title,
            "content": chunk_text,
            "content_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
        })
    return result


def main():
    """主函数：加载 ag_news 数据集，分块后写入 Milvus"""
    parser = argparse.ArgumentParser(description="Seed ag_news data into Milvus")
    parser.add_argument("--limit", type=int, default=10000, help="Number of articles to load")
    parser.add_argument("--chunk-size", type=int, default=500, help="Chunk size for text splitting")
    parser.add_argument("--user-id", type=str, default="", help="User ID for tenant isolation")
    parser.add_argument("--company-id", type=str, default="", help="Company ID for tenant isolation")
    args = parser.parse_args()

    chunk_overlap = max(50, args.chunk_size // 10)
    logger.info("seeding_data_started", limit=args.limit, chunk_size=args.chunk_size)

    try:
        # 初始化 Milvus store
        store = MilvusStore()
        store.create_collection(drop_existing=True)
        logger.info("milvus_collection_ready")

        # 加载数据集（打乱顺序以覆盖所有类别）
        logger.info("loading_dataset", dataset="fancyzhx/ag_news")
        dataset = load_dataset("fancyzhx/ag_news", split="train", streaming=True)
        from itertools import islice
        dataset = list(islice(dataset.shuffle(seed=42), args.limit))
        logger.info("dataset_loaded", count=len(dataset))

        # 第一步：分块，收集所有 chunk 文本
        all_chunks: list[dict] = []
        categories = ["World", "Sports", "Business", "Sci/Tech"]

        for row in dataset:
            text = row["text"]
            title = text[:100]
            category = categories[row["label"]]
            chunks = chunk_article(text, title, args.chunk_size, chunk_overlap)
            for c in chunks:
                c["source"] = "ag_news"
                c["language"] = "en"
                c["category"] = category
                c["published_at"] = 0
                if args.user_id:
                    c["user_id"] = args.user_id
                if args.company_id:
                    c["company_id"] = args.company_id
            all_chunks.extend(chunks)

        logger.info("chunking_done", articles=len(dataset), chunks=len(all_chunks))
        print(f"分块完成: {len(dataset)} 篇文章 → {len(all_chunks)} 个 chunks", flush=True)

        # 第二步：批量 embedding 并插入
        batch_size = 50
        for i in tqdm(range(0, len(all_chunks), batch_size), desc="Embedding & inserting", unit="batch"):
            batch = all_chunks[i:i + batch_size]
            texts = [c["content"] for c in batch]

            try:
                embeddings = embed_texts(texts)
                records = []
                for j, chunk in enumerate(batch):
                    chunk["embedding"] = embeddings[j]
                    records.append(chunk)

                store.insert(records)
                logger.debug("batch_inserted", batch=i // batch_size + 1, count=len(records))

            except Exception as e:
                logger.error("batch_insert_failed", batch=i // batch_size + 1, error=str(e))
                continue

        # 输出最终统计
        total = store.count()
        logger.info("seeding_completed", total=total, articles=len(dataset), chunks=len(all_chunks))
        print(f"\n导入完成: {len(dataset)} 篇文章 → {total} 个 chunks")

    except Exception as e:
        logger.error("seeding_failed", error=str(e))
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()