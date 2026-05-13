"""
Milvus Chunk Collection - 存储文章切分后的 chunk
"""
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from core import get_logger, settings

logger = get_logger(__name__)

CHUNK_COLLECTION_NAME = "news_chunks"
DIM = 1024  # BGE-large-zh embedding dimension


def get_milvus_connection():
    """Get or create Milvus connection."""
    alias = "chunk_store"
    if not connections.has_connection(alias):
        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=settings.milvus_port,
            user=settings.milvus_user or None,
            password=settings.milvus_password or None,
        )
    return alias


def create_chunk_schema() -> CollectionSchema:
    """Create the news_chunks collection schema."""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="article_id", dtype=DataType.INT64, description="关联原始文章 ID"),
        FieldSchema(name="chunk_index", dtype=DataType.INT32, description="chunk 在文章内的顺序"),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512, description="文章标题"),
        FieldSchema(name="pub_time", dtype=DataType.VARCHAR, max_length=32, description="发布时间"),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=64, description="来源"),
        FieldSchema(name="lead", dtype=DataType.VARCHAR, max_length=2048, description="导语（可能为空）"),
        FieldSchema(
            name="content",
            dtype=DataType.VARCHAR,
            max_length=4096,
            description="固定头部 + 正文片段",
        ),
        FieldSchema(name="content_hash", dtype=DataType.VARCHAR, max_length=64, description="chunk 内容 hash"),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=DIM, description="embedding 向量"),
    ]
    return CollectionSchema(fields=fields, description="News article chunks collection")


class ChunkStore:
    """Milvus chunk store operations."""

    def __init__(self, collection_name: str = CHUNK_COLLECTION_NAME):
        self.collection_name = collection_name
        self._collection: Collection | None = None
        self.alias = get_milvus_connection()

    @property
    def collection(self) -> Collection:
        """Get or load the collection."""
        if self._collection is None:
            if not utility.has_collection(self.collection_name, using=self.alias):
                self.create_collection()
            self._collection = Collection(self.collection_name, using=self.alias)
            self._collection.load()
        return self._collection

    def create_collection(self, drop_existing: bool = False) -> None:
        """Create the chunks collection with indexes."""
        if utility.has_collection(self.collection_name, using=self.alias):
            if drop_existing:
                utility.drop_collection(self.collection_name, using=self.alias)
                logger.info("chunk_collection_dropped", name=self.collection_name)
            else:
                logger.info("chunk_collection_exists", name=self.collection_name)
                self._collection = Collection(self.collection_name, using=self.alias)
                self._collection.load()
                return

        schema = create_chunk_schema()
        self._collection = Collection(name=self.collection_name, schema=schema, using=self.alias)

        # Create vector index
        index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
            "params": {"nlist": 128},
        }
        self._collection.create_index(field_name="embedding", index_params=index_params)

        # Create index on article_id for grouping
        try:
            self._collection.create_index(
                field_name="article_id",
                index_params={"index_type": "STL_SORT"},
            )
        except Exception as e:
            logger.warning("article_id_index_creation_failed", error=str(e))

        # Create index on content_hash for deduplication
        try:
            self._collection.create_index(
                field_name="content_hash",
                index_params={"index_type": "STL_SORT"},
            )
        except Exception as e:
            logger.warning("content_hash_index_creation_failed", error=str(e))

        self._collection.load()
        logger.info("chunk_collection_created", name=self.collection_name)

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> list[int]:
        """
        批量插入 chunks

        Args:
            chunks: list of chunk dicts with keys:
                - article_id: int
                - chunk_index: int
                - title: str
                - pub_time: str
                - source: str
                - lead: str
                - content: str
                - content_hash: str
                - embedding: list[float]

        Returns:
            list of inserted primary keys
        """
        if not chunks:
            return []

        # 转换为 entity 格式，按 schema 顺序排列
        # Schema: id, article_id, chunk_index, title, pub_time, source, lead, content, content_hash, embedding
        entities = [
            [c.get("article_id", 0) for c in chunks],
            [c.get("chunk_index", 0) for c in chunks],
            [c.get("title", "") for c in chunks],
            [c.get("pub_time", "") for c in chunks],
            [c.get("source", "") for c in chunks],
            [c.get("lead", "") for c in chunks],
            [c.get("content", "") for c in chunks],
            [c.get("content_hash", "") for c in chunks],
            [c.get("embedding", [0.0] * DIM) for c in chunks],
        ]

        result = self.collection.insert(entities)
        self.collection.flush()
        logger.info("chunks_inserted", count=len(chunks), ids=result.primary_keys)
        return result.primary_keys

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        expr: str | None = None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search chunks by vector similarity."""
        if output_fields is None:
            output_fields = [
                "article_id",
                "chunk_index",
                "title",
                "pub_time",
                "source",
                "lead",
                "content",
            ]

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

    def query_by_article(self, article_id: int, output_fields: list[str] | None = None) -> list[dict[str, Any]]:
        """Query all chunks for a specific article."""
        if output_fields is None:
            output_fields = [
                "article_id",
                "chunk_index",
                "title",
                "pub_time",
                "source",
                "lead",
                "content",
            ]

        expr = f"article_id == {article_id}"
        results = self.collection.query(expr=expr, output_fields=output_fields, limit=1000)
        return results

    def check_hash_exists(self, content_hash: str) -> bool:
        """Check if a chunk with given content_hash already exists."""
        expr = f'content_hash == "{content_hash}"'
        results = self.collection.query(expr=expr, output_fields=["id"], limit=1)
        return len(results) > 0

    def upsert_chunk(self, chunk: dict[str, Any]) -> None:
        """Insert a single chunk (wrapper around insert_chunks)."""
        self.insert_chunks([chunk])

    def count(self) -> int:
        """Get total chunk count."""
        return self.collection.num_entities

    def stats(self) -> str:
        """返回存储统计信息"""
        return f"chunks={self.count()}"

    def delete_by_ids(self, ids: list[int]) -> None:
        """Delete entities by IDs."""
        expr = f"id in {ids}"
        self.collection.delete(expr)
        self.collection.flush()

    def drop_collection(self) -> None:
        """Drop the entire collection."""
        if utility.has_collection(self.collection_name, using=self.alias):
            utility.drop_collection(self.collection_name, using=self.alias)
            self._collection = None
            logger.info("chunk_collection_dropped", name=self.collection_name)
