from typing import Any
import asyncio
import hashlib

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from core import get_logger, settings, VectorStoreError
from ._common import DIM, get_milvus_connection

logger = get_logger(__name__)

COLLECTION_NAME = "news_articles"


def compute_content_hash(record: dict[str, Any]) -> str:
    """Compute a stable deduplication hash for a news record."""
    content_str = f"{record.get('title', '')}|{record.get('content', '')}"
    return hashlib.sha256(content_str.encode()).hexdigest()


def filter_new_records_by_hash(
    records: list[dict[str, Any]],
    existing_hashes: set[str],
) -> list[dict[str, Any]]:
    """Remove records already seen in storage or earlier in the same batch."""
    seen = set(existing_hashes)
    filtered = []
    for record in records:
        content_hash = record.get("content_hash") or compute_content_hash(record)
        if content_hash in seen:
            continue
        record["content_hash"] = content_hash
        seen.add(content_hash)
        filtered.append(record)
    return filtered


def create_schema() -> CollectionSchema:
    """Create the news_articles collection schema."""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=DIM),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="language", dtype=DataType.VARCHAR, max_length=10),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="published_at", dtype=DataType.INT64),
        FieldSchema(name="content_hash", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="url", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="author", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="external_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="fetched_at", dtype=DataType.INT64),
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="parent_doc_id", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="company_id", dtype=DataType.VARCHAR, max_length=64),
    ]
    return CollectionSchema(fields=fields, description="News articles collection")


class MilvusStore:
    """Milvus vector store operations."""

    def __init__(self, collection_name: str = COLLECTION_NAME):
        self.collection_name = collection_name
        self._collection: Collection | None = None
        get_milvus_connection()

    @property
    def collection(self) -> Collection:
        """Get or load the collection."""
        if self._collection is None:
            if not utility.has_collection(self.collection_name):
                self.create_collection()
            self._collection = Collection(self.collection_name)
            self._collection.load()
        return self._collection

    def create_collection(self, drop_existing: bool = False) -> None:
        """Create the collection with indexes."""
        if utility.has_collection(self.collection_name):
            if drop_existing:
                utility.drop_collection(self.collection_name)
                logger.info("collection_dropped", name=self.collection_name)
            else:
                logger.info("collection_exists", name=self.collection_name)
                self._collection = Collection(self.collection_name)
                self._collection.load()
                return

        schema = create_schema()
        self._collection = Collection(name=self.collection_name, schema=schema)

        # Create vector index
        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
            "params": {"nlist": 128},
        }
        self._collection.create_index(field_name="embedding", index_params=index_params)

        # Create fulltext index on title and content
        # Note: Requires Milvus 2.4+ for fulltext index
        try:
            self._collection.create_index(
                field_name="title",
                index_params={"index_type": "STL_SORT"},
            )
            self._collection.create_index(
                field_name="content",
                index_params={"index_type": "STL_SORT"},
            )
        except Exception as e:
            logger.warning("scalar_index_creation_failed", error=str(e))

        self._collection.load()
        logger.info("collection_created", name=self.collection_name)

    def insert(self, records: list[dict[str, Any]]) -> list[int]:
        """Insert records into collection."""
        for record in records:
            # Compute content hash for deduplication
            record["content_hash"] = compute_content_hash(record)

        records = self._filter_existing_records(records)
        if not records:
            logger.info("records_insert_skipped_all_duplicates")
            return []

        entities = [
            [r.get("title", "") for r in records],
            [r.get("content", "") for r in records],
            [r.get("source", "") for r in records],
            [r.get("language", "") for r in records],
            [r.get("category", "") for r in records],
            [r.get("published_at", 0) for r in records],
            [r.get("content_hash", "") for r in records],
            [r.get("embedding", [0.0] * DIM) for r in records],
            [r.get("url", "") for r in records],
            [r.get("author", "") for r in records],
            [r.get("external_id", "") for r in records],
            [r.get("fetched_at", 0) for r in records],
            [r.get("chunk_id", "") for r in records],
            [r.get("parent_doc_id", "") for r in records],
            [r.get("user_id", "") for r in records],
            [r.get("company_id", "") for r in records],
        ]

        insert_entities = [
            entities[7],  # embedding
            entities[0],  # title
            entities[1],  # content
            entities[2],  # source
            entities[3],  # language
            entities[4],  # category
            entities[5],  # published_at
            entities[6],  # content_hash
            entities[8],  # url
            entities[9],  # author
            entities[10],  # external_id
            entities[11],  # fetched_at
            entities[12],  # chunk_id
            entities[13],  # parent_doc_id
            entities[14],  # user_id
            entities[15],  # company_id
        ]

        result = self.collection.insert(insert_entities)
        self.collection.flush()
        logger.info("records_inserted", count=len(records), ids=result.primary_keys)
        return result.primary_keys

    def _filter_existing_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        hashes = [record["content_hash"] for record in records]
        if not hashes:
            return records

        quoted_hashes = ", ".join(f'"{content_hash}"' for content_hash in hashes)
        try:
            existing = self.query(
                expr=f"content_hash in [{quoted_hashes}]",
                output_fields=["content_hash"],
                limit=len(hashes),
            )
        except Exception as e:
            logger.warning("content_hash_lookup_failed", error=str(e))
            existing = []

        existing_hashes = {item.get("content_hash", "") for item in existing}
        filtered = filter_new_records_by_hash(records, existing_hashes)
        skipped = len(records) - len(filtered)
        if skipped:
            logger.info("duplicate_records_skipped", count=skipped)
        return filtered

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        expr: str | None = None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search by vector similarity."""
        if output_fields is None:
            output_fields = [
                "title", "content", "source", "language", "category", "published_at",
                "content_hash", "url", "author", "external_id", "chunk_id", "parent_doc_id",
                "user_id", "company_id",
            ]

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        try:
            results = self.collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=expr,
                output_fields=output_fields,
            )
        except Exception as e:
            logger.error("milvus_search_failed", error=str(e))
            raise VectorStoreError(f"Vector search failed: {e}") from e

        hits = []
        for hits_list in results:
            for hit in hits_list:
                record = {field: hit.entity.get(field) for field in output_fields}
                record["score"] = hit.score
                record["id"] = hit.id
                hits.append(record)
        return hits

    def query(self, expr: str, output_fields: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Query by expression."""
        if output_fields is None:
            output_fields = [
                "title", "content", "source", "language", "category", "published_at",
                "content_hash", "url", "author", "external_id", "chunk_id", "parent_doc_id",
                "user_id", "company_id",
            ]

        try:
            results = self.collection.query(expr=expr, output_fields=output_fields, limit=limit)
        except Exception as e:
            logger.error("milvus_query_failed", error=str(e))
            raise VectorStoreError(f"Vector query failed: {e}") from e
        return results

    def count(self) -> int:
        """Get total entity count."""
        try:
            return self.collection.num_entities
        except Exception as e:
            logger.error("milvus_count_failed", error=str(e))
            raise VectorStoreError(f"Vector count failed: {e}") from e

    def delete_by_ids(self, ids: list[int]) -> None:
        """Delete entities by IDs."""
        expr = f"id in {ids}"
        self.collection.delete(expr)
        self.collection.flush()

    def drop_collection(self) -> None:
        """Drop the entire collection."""
        if utility.has_collection(self.collection_name):
            utility.drop_collection(self.collection_name)
            self._collection = None
            logger.info("collection_dropped", name=self.collection_name)

    # --- Async wrappers (avoid blocking the event loop) ---

    async def search_async(self, **kwargs) -> list[dict[str, Any]]:
        """Async wrapper for search()."""
        return await asyncio.to_thread(self.search, **kwargs)

    async def query_async(self, **kwargs) -> list[dict[str, Any]]:
        """Async wrapper for query()."""
        return await asyncio.to_thread(self.query, **kwargs)

    async def insert_async(self, records: list[dict[str, Any]]) -> list[int]:
        """Async wrapper for insert()."""
        return await asyncio.to_thread(self.insert, records)
