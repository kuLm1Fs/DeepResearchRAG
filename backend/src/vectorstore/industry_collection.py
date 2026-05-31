"""ai_industry_articles Milvus Collection 管理"""

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
from ._common import DIM, get_milvus_connection

logger = get_logger(__name__)


def _escape_milvus_str(value: Any) -> str:
    """Escape string content for Milvus scalar equality filters."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')

COLLECTION_NAME = "ai_industry_articles"


def create_schema() -> CollectionSchema:
    """Create the ai_industry_articles collection schema (15 fields)."""
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=DIM),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="author", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="tags", dtype=DataType.JSON),
        FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="language", dtype=DataType.VARCHAR, max_length=10),
        FieldSchema(name="published_at", dtype=DataType.INT64),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="company_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="domain", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="content_hash", dtype=DataType.VARCHAR, max_length=64),
    ]
    return CollectionSchema(
        fields=fields,
        description="AI industry articles collection for deep research"
    )


class IndustryCollection:
    """ai_industry_articles collection 操作类"""

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
        """Create collection with indexes."""
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
        self._collection = Collection(
            name=self.collection_name,
            schema=schema,
            description="AI industry articles collection for deep research"
        )

        # 向量索引
        vector_index_params = {
            "index_type": "IVF_FLAT",
            "metric_type": "COSINE",
            "params": {"nlist": 128},
        }
        self._collection.create_index(
            field_name="embedding",
            index_params=vector_index_params,
        )

        # user_id 索引（多用户隔离查询）- VARCHAR 使用 INVERTED 索引
        self._collection.create_index(
            field_name="user_id",
            index_params={"index_type": "INVERTED"},
        )

        # published_at 索引（时间范围查询）
        self._collection.create_index(
            field_name="published_at",
            index_params={"index_type": "STL_SORT"},
        )

        self._collection.load()
        logger.info("collection_created", name=self.collection_name)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        user_id: str | None = None,
        company_id: str | None = None,
        filters: dict[str, Any] | None = None,
        output_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search similar articles, filtered by user_id and/or company_id."""
        if output_fields is None:
            output_fields = [
                "id", "title", "content", "summary", "source",
                "category", "language", "published_at", "user_id", "company_id",
            ]

        expr_parts = []
        if user_id:
            expr_parts.append(f'user_id == "{_escape_milvus_str(user_id)}"')
        if company_id:
            expr_parts.append(f'company_id == "{_escape_milvus_str(company_id)}"')
        if filters:
            for key, val in filters.items():
                if isinstance(val, str):
                    expr_parts.append(f'{key} == "{_escape_milvus_str(val)}"')
                else:
                    expr_parts.append(f"{key} == {val}")

        expr = " && ".join(expr_parts) if expr_parts else None

        results = self.collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"nprobe": 10}},
            limit=top_k,
            expr=expr,
            output_fields=output_fields,
        )
        return [hit.to_dict() for hit in results[0]]

    def insert(self, data: list[dict[str, Any]]) -> list[int]:
        """Insert articles into collection."""
        return self.collection.insert(data)[0]

    def upsert(self, data: list[dict[str, Any]]) -> list[int]:
        """Upsert articles (insert or update by content_hash)."""
        return self.collection.upsert(data)[0]

    def delete_by_user_id(self, user_id: str) -> int:
        """Delete all articles for a user."""
        expr = f'user_id == "{_escape_milvus_str(user_id)}"'
        result = self.collection.delete(expr)
        self.collection.flush()
        return result

    def count(self, user_id: str | None = None, company_id: str | None = None) -> int:
        """Count articles, optionally filtered by user_id and/or company_id."""
        expr_parts = []
        if user_id:
            expr_parts.append(f'user_id == "{_escape_milvus_str(user_id)}"')
        if company_id:
            expr_parts.append(f'company_id == "{_escape_milvus_str(company_id)}"')
        if expr_parts:
            expr = " && ".join(expr_parts)
            return self.collection.query(expr, output_fields=["count(*)"])[0]["count(*)"]
        return self.collection.num_entities