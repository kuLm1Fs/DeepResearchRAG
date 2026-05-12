from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from core import get_logger, settings, VectorStoreError

logger = get_logger(__name__)

COLLECTION_NAME = "news_articles"
DIM = 1024


def get_milvus_connection():
    """Get or create Milvus connection."""
    alias = "default"
    if not connections.has_connection(alias):
        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=settings.milvus_port,
            user=settings.milvus_user or None,
            password=settings.milvus_password or None,
        )
    return alias


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
        except Exception as e:
            logger.warning("title_index_creation_failed", error=str(e))

        self._collection.load()
        logger.info("collection_created", name=self.collection_name)

    def insert(self, records: list[dict[str, Any]]) -> list[int]:
        """Insert records into collection."""
        import hashlib

        for record in records:
            # Compute content hash for deduplication
            content_str = f"{record['title']}|{record['content']}"
            record["content_hash"] = hashlib.sha256(content_str.encode()).hexdigest()

        entities = [
            [r.get("title", "") for r in records],
            [r.get("content", "") for r in records],
            [r.get("source", "") for r in records],
            [r.get("language", "") for r in records],
            [r.get("category", "") for r in records],
            [r.get("published_at", 0) for r in records],
            [r.get("content_hash", "") for r in records],
            [r.get("embedding", [0.0] * DIM) for r in records],
        ]

        # Note: Schema uses auto_id, so we can't include 'id' field in insert
        # Re-order to match schema: id, embedding, title, content, source, language, category, published_at, content_hash
        insert_entities = [
            entities[7],  # embedding
            entities[0],  # title
            entities[1],  # content
            entities[2],  # source
            entities[3],  # language
            entities[4],  # category
            entities[5],  # published_at
            entities[6],  # content_hash
        ]

        result = self.collection.insert(insert_entities)
        self.collection.flush()
        logger.info("records_inserted", count=len(records), ids=result.primary_keys)
        return result.primary_keys

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        expr: str | None = None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search by vector similarity."""
        if output_fields is None:
            output_fields = ["title", "content", "source", "language", "category", "published_at"]

        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        results = self.collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=output_fields,
        )

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
            output_fields = ["title", "content", "source", "language", "category", "published_at"]

        results = self.collection.query(expr=expr, output_fields=output_fields, limit=limit)
        return results

    def count(self) -> int:
        """Get total entity count."""
        return self.collection.num_entities

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