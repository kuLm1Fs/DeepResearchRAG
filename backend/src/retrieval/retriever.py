from typing import Any

from core import get_logger, settings, RetrievalError
from vectorstore import MilvusStore, embed_texts_async
from .fusion import reciprocal_rank_fusion

logger = get_logger(__name__)


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
    ):
        self.store = store
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.title_weight = title_weight
        self.semantic_limit = semantic_limit
        self.keyword_limit = keyword_limit
        self.title_limit = title_limit

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
            # Path 1: Semantic vector search
            semantic_results = await self._semantic_search(query)

            # Path 2: Keyword search
            keyword_results = await self._keyword_search(query)

            # Path 3: Title exact match
            title_results = await self._title_match(query)

            # Apply filters if provided
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

            # Return top_k
            final_results = fused[:top_k]

            logger.info("retrieval_completed",
                query=query,
                result_count=len(final_results),
            )

            return final_results

        except Exception as e:
            logger.error("retrieval_failed", query=query, error=str(e))
            raise RetrievalError(f"Retrieval failed: {e}")

    async def _semantic_search(self, query: str) -> list[dict[str, Any]]:
        """Vector similarity search."""
        try:
            query_embedding = (await embed_texts_async([query]))[0]
            return self.store.search(
                query_embedding=query_embedding,
                top_k=self.semantic_limit,
            )
        except Exception as e:
            logger.warning("semantic_search_failed", error=str(e))
            return []

    async def _keyword_search(self, query: str) -> list[dict[str, Any]]:
        """Keyword/fulltext search on title and content."""
        try:
            # 搜索 title 和 content 两个字段，使用 OR 条件
            results = self.store.query(
                expr=f'title like "%{query}%" or content like "%{query}%"',
                output_fields=["title", "content", "source", "language", "category", "published_at", "id"],
                limit=self.keyword_limit,
            )
            # 添加默认分数
            for r in results:
                r["score"] = 0.5
            return results
        except Exception as e:
            logger.warning("keyword_search_failed", error=str(e))
            return []

    async def _title_match(self, query: str) -> list[dict[str, Any]]:
        """Exact title matching."""
        try:
            results = self.store.query(
                expr=f'title like "%{query}%"',
                output_fields=["title", "content", "source", "language", "category", "published_at", "id"],
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
            filtered.append(r)
        return filtered