#!/usr/bin/env python3
"""Seed data from HuggingFace ag_news dataset into Milvus."""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datasets import load_dataset

from core import configure_logging, get_logger, settings
from vectorstore import MilvusStore
from vectorstore.embedding import embed_texts

configure_logging()
logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Seed ag_news data into Milvus")
    parser.add_argument("--limit", type=int, default=10000, help="Number of articles to load")
    args = parser.parse_args()

    logger.info("seeding_data_started", limit=args.limit)

    # Initialize Milvus store
    store = MilvusStore()
    store.create_collection(drop_existing=True)

    # Load dataset
    dataset = load_dataset("fancyzhx/ag_news", split=f"train[:{args.limit}]")
    logger.info("dataset_loaded", count=len(dataset))

    # Process and insert in batches
    batch_size = 50
    for i in range(0, len(dataset), batch_size):
        batch = dataset[i:i+batch_size]
        texts = [f"{item['title']} - {item['description']}" for item in batch]

        # Get embeddings
        embeddings = embed_texts(texts)

        # Prepare records
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
        logger.info("batch_inserted", batch=i//batch_size + 1, count=len(records))

    logger.info("seeding_completed", total=store.count())


if __name__ == "__main__":
    main()