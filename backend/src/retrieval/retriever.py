from typing import Any

from core import RetrievalError, get_logger
from vectorstore import MilvusStore, embed_texts_async

from .boost import boost_results
from .fusion import reciprocal_rank_fusion
from .reranker import CrossEncoderReranker

logger = get_logger(__name__)


def escape_milvus_like_value(value: str) -> str:
    """Escape user-controlled content before embedding it in a Milvus LIKE expr."""
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def build_like_expr(fields: list[str], query: str) -> str:
    escaped_query = escape_milvus_like_value(query)
    return " or ".join(f'{field} like "%{escaped_query}%"' for field in fields)


def escape_milvus_string_value(value: Any) -> str:
    """Escape string content for scalar equality filters."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def build_filter_expr(filters: dict[str, Any] | None) -> str | None:
    """Build a Milvus scalar expr for trusted filter fields."""
    if not filters:
        return None

    allowed_fields = {"language", "category", "source", "user_id", "company_id"}
    clauses = []
    for field, value in filters.items():
        if field not in allowed_fields or value is None or value == "":
            continue
        clauses.append(f'{field} == "{escape_milvus_string_value(value)}"')

    # Range filters for published_at (epoch seconds)
    date_from = filters.get("published_at_from")
    date_to = filters.get("published_at_to")
    if date_from is not None:
        clauses.append(f"published_at >= {int(date_from)}")
    if date_to is not None:
        clauses.append(f"published_at <= {int(date_to)}")

    return " and ".join(clauses) if clauses else None


def combine_expr(base_expr: str | None, filter_expr: str | None) -> str | None:
    if base_expr and filter_expr:
        return f"({base_expr}) and {filter_expr}"
    return base_expr or filter_expr


class MultiPathRetriever:
    """
    Multi-path retriever combining semantic, keyword, and title-match retrieval.

    Paths:
    1. Semantic: Vector similarity search
    2. Keyword: Fulltext search on title and content
    3. Title match: Exact/near-exact title matching

    Results are fused using RRF (Reciprocal Rank Fusion).
    """

    def __init__(
        self,
        store: MilvusStore,
        semantic_weight: float = 0.5,
        keyword_weight: float = 0.3,
        title_weight: float = 0.2,
        semantic_limit: int = 20,
        keyword_limit: int = 20,
        title_limit: int = 10,
        rerank_enabled: bool = True,
        rerank_candidate_multiplier: int = 4,
    ):
        self.store = store
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.title_weight = title_weight
        self.semantic_limit = semantic_limit
        self.keyword_limit = keyword_limit
        self.title_limit = title_limit
        self.rerank_enabled = rerank_enabled
        self.rerank_candidate_multiplier = rerank_candidate_multiplier
        self.reranker = CrossEncoderReranker()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant documents using multi-path search.

        Args:
            query: Search query text
            top_k: Number of final results to return
            filters: Optional filters (language, category, source, etc.)

        Returns:
            List of relevant documents with scores
        """
        logger.info("retrieval_started",
            query=query,
            top_k=top_k,
            filters=filters,
        )

        try:
            filter_expr = build_filter_expr(filters)

            # Path 1: Semantic vector search
            semantic_results = await self._semantic_search(query, filter_expr=filter_expr)

            # Path 2: Keyword search
            keyword_results = await self._keyword_search(query, filter_expr=filter_expr)

            # Path 3: Title exact match
            title_results = await self._title_match(query, filter_expr=filter_expr)

            # Keep an in-process filter as a defensive check for test fakes or stores
            # that do not enforce scalar expressions.
            if filters:
                semantic_results = self._apply_filters(semantic_results, filters)
                keyword_results = self._apply_filters(keyword_results, filters)
                title_results = self._apply_filters(title_results, filters)

            # Log individual path results
            logger.info("paths_completed",
                semantic_count=len(semantic_results),
                keyword_count=len(keyword_results),
                title_count=len(title_results),
            )

            # RRF fusion
            fused = reciprocal_rank_fusion(
                [semantic_results, keyword_results, title_results],
                weights=[self.semantic_weight, self.keyword_weight, self.title_weight],
                k=60,
            )

            # Apply boost (time decay + source quality)
            boosted = boost_results(
                fused,
                use_time_decay=True,
                use_source_quality=True,
                time_weight=0.3,
                source_weight=0.2,
            )

            if self.rerank_enabled:
                candidate_limit = max(top_k, top_k * self.rerank_candidate_multiplier)
                final_results = self.reranker.rerank(query, boosted[:candidate_limit], top_k)
            else:
                final_results = boosted[:top_k]

            logger.info("retrieval_completed",
                query=query,
                result_count=len(final_results),
            )

            return final_results

        except Exception as e:
            logger.error("retrieval_failed", query=query, error=str(e))
            raise RetrievalError(f"Retrieval failed: {e}")

    async def _semantic_search(
        self,
        query: str,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search."""
        try:
            query_embedding = (await embed_texts_async([query]))[0]
            return self.store.search(
                query_embedding=query_embedding,
                top_k=self.semantic_limit,
                expr=filter_expr,
            )
        except Exception as e:
            logger.warning("semantic_search_failed", error=str(e))
            return []

    async def _keyword_search(
        self,
        query: str,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Keyword/fulltext search on title and content."""
        try:
            # 搜索 title 和 content 两个字段，使用 OR 条件
            results = self.store.query(
                expr=combine_expr(build_like_expr(["title", "content"], query), filter_expr),
                output_fields=[
                    "title", "content", "source", "language", "category", "published_at",
                    "content_hash", "id", "user_id", "company_id", "url",
                ],
                limit=self.keyword_limit,
            )
            # 添加默认分数
            for r in results:
                r["score"] = 0.5
            return results
        except Exception as e:
            logger.warning("keyword_search_failed", error=str(e))
            return []

    async def _title_match(
        self,
        query: str,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Exact title matching."""
        try:
            results = self.store.query(
                expr=combine_expr(build_like_expr(["title"], query), filter_expr),
                output_fields=[
                    "title", "content", "source", "language", "category", "published_at",
                    "content_hash", "id", "user_id", "company_id", "url",
                ],
                limit=self.title_limit,
            )
            for r in results:
                r["score"] = 0.8
            return results
        except Exception as e:
            logger.warning("title_match_failed", error=str(e))
            return []

    def _apply_filters(self, results: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Apply filters to results."""
        filtered = []
        for r in results:
            if "language" in filters and r.get("language") != filters["language"]:
                continue
            if "category" in filters and r.get("category") != filters["category"]:
                continue
            if "source" in filters and r.get("source") != filters["source"]:
                continue
            if "user_id" in filters and r.get("user_id") != filters["user_id"]:
                continue
            if "company_id" in filters and r.get("company_id") != filters["company_id"]:
                continue
            # Range filter for published_at
            published_at = r.get("published_at")
            if published_at is not None:
                if "published_at_from" in filters and published_at < filters["published_at_from"]:
                    continue
                if "published_at_to" in filters and published_at > filters["published_at_to"]:
                    continue
            filtered.append(r)
        return filtered
