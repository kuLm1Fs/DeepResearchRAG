#!/usr/bin/env python3
"""Initialize ai_industry_articles collection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from vectorstore.industry_collection import IndustryCollection


def main():
    collection = IndustryCollection()
    collection.create_collection(drop_existing=False)
    count = collection.count()
    print(f"ai_industry_articles collection ready. Total articles: {count}")


if __name__ == "__main__":
    main()