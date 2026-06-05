import asyncio
import re
import time
from typing import TYPE_CHECKING, Any

from core import RetrievalError, get_logger
from core.degradation import DegradationPolicy
from core.fault_injection import FaultInjector
from core.metrics import metrics_registry
from vectorstore import MilvusStore, embed_texts_async

from .boost import boost_results
from .fusion import reciprocal_rank_fusion
from .reranker import CrossEncoderReranker

if TYPE_CHECKING:
    from .graph_retriever import GraphRetriever

logger = get_logger(__name__)

_LIKE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9&./-]{1,63}|[\u4e00-\u9fff]{2,}")
_LIKE_STOPWORDS = {
    "and", "are", "but", "did", "does", "for", "from", "had", "has", "have",
    "in", "include", "includes", "into", "its", "of", "percent", "the",
    "their", "this", "total", "was", "were", "what", "when", "where",
    "which", "with",
}


def escape_milvus_like_value(value: str) -> str:
    """Escape user-controlled content before embedding it in a Milvus LIKE expr."""
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def extract_like_terms(query: str, max_terms: int = 8) -> list[str]:
    """Extract short Milvus LIKE-safe terms instead of querying with a raw sentence."""
    terms: list[str] = []
    seen: set[str] = set()
    for match in _LIKE_TOKEN_RE.finditer(query):
        term = match.group(0).strip(".-/")
        if match.end() < len(query) and query[match.end()] == "%":
            continue
        if len(term) < 2:
            continue
        key = term.lower()
        if key in _LIKE_STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


def build_like_expr(fields: list[str], query: str) -> str | None:
    terms = extract_like_terms(query)
    if not terms:
        return None

    clauses = []
    for term in terms:
        escaped_term = escape_milvus_like_value(term)
        clauses.extend(f'{field} like "%{escaped_term}%"' for field in fields)
    return " or ".join(clauses)


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
    Multi-path retriever combining semantic, keyword, title-match, and (optional) graph retrieval.

    Paths:
    1. Semantic: Vector similarity search (Milvus)
    2. Keyword: Fulltext search on title and content (Milvus)
    3. Title match: Exact/near-exact title matching (Milvus)
    4. Graph (optional, Phase 3 of GraphRAG): Dual-level entity+relation
       search over Neo4j, fed back as a 4th ranked list for RRF fusion.

    Results are fused using RRF (Reciprocal Rank Fusion). When the graph
    path is enabled its weight is taken from the same ratio as the other
    three, with semantic down-weighted to make room.
    """

    def __init__(
        self,
        store: MilvusStore,
        semantic_weight: float = 0.4,
        keyword_weight: float = 0.2,
        title_weight: float = 0.15,
        graph_weight: float = 0.25,
        semantic_limit: int = 20,
        keyword_limit: int = 20,
        title_limit: int = 10,
        graph_limit: int = 10,
        rerank_enabled: bool = True,
        rerank_candidate_multiplier: int = 4,
        graph_retriever: "GraphRetriever | None" = None,
        fault_injector: FaultInjector | None = None,
        degradation_policy: DegradationPolicy | None = None,
    ):
        self.store = store
        self.semantic_weight = semantic_weight
        self.keyword_weight = keyword_weight
        self.title_weight = title_weight
        self.graph_weight = graph_weight
        self.semantic_limit = semantic_limit
        self.keyword_limit = keyword_limit
        self.title_limit = title_limit
        self.graph_limit = graph_limit
        self.rerank_enabled = rerank_enabled
        self.rerank_candidate_multiplier = rerank_candidate_multiplier
        self.reranker = CrossEncoderReranker()
        self.graph_retriever = graph_retriever
        self.fault_injector = fault_injector or FaultInjector()
        self.degradation_policy = degradation_policy or DegradationPolicy()

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        strategy: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """
        Retrieve relevant documents using multi-path search.

        Args:
            query: Search query text
            top_k: Number of final results to return
            filters: Optional filters (language, category, source, etc.)
            strategy: One of "hybrid" (default), "vector" (skip graph), or
                "graph" (only graph path, no Milvus). Phase 4 routes by
                intent; this is the API surface for that decision.

        Returns:
            List of relevant documents with scores
        """
        logger.info("retrieval_started",
            query=query,
            top_k=top_k,
            filters=filters,
            strategy=strategy,
        )

        started = time.perf_counter()
        try:
            filter_expr = build_filter_expr(filters)

            # Strategy dispatch. "vector" runs only the three Milvus
            # paths; "graph" runs only the graph path; "hybrid" runs all
            # four with RRF fusion.
            if strategy == "vector":
                semantic_results, keyword_results, title_results = await asyncio.gather(
                    self._semantic_search(query, filter_expr=filter_expr),
                    self._keyword_search(query, filter_expr=filter_expr),
                    self._title_match(query, filter_expr=filter_expr),
                )
                graph_results: list[dict[str, Any]] = []
            elif strategy == "graph":
                semantic_results, keyword_results, title_results = [], [], []
                graph_results = await self._graph_search(query) if self.graph_retriever else []
            else:  # hybrid
                tasks = [
                    self._semantic_search(query, filter_expr=filter_expr),
                    self._keyword_search(query, filter_expr=filter_expr),
                    self._title_match(query, filter_expr=filter_expr),
                ]
                if self.graph_retriever:
                    tasks.append(self._graph_search(query))
                gathered = await asyncio.gather(*tasks)
                semantic_results, keyword_results, title_results = gathered[0], gathered[1], gathered[2]
                graph_results = gathered[3] if self.graph_retriever else []

            # Keep an in-process filter as a defensive check for test fakes or stores
            # that do not enforce scalar expressions.
            if filters:
                semantic_results = self._apply_filters(semantic_results, filters)
                keyword_results = self._apply_filters(keyword_results, filters)
                title_results = self._apply_filters(title_results, filters)
                # graph_results come from Neo4j which doesn't know about
                # user_id/company_id yet; skip filter there.

            # Log individual path results
            logger.info("paths_completed",
                semantic_count=len(semantic_results),
                keyword_count=len(keyword_results),
                title_count=len(title_results),
                graph_count=len(graph_results),
                strategy=strategy,
            )

            # RRF fusion
            if strategy == "graph":
                # Single-path shortcut — no fusion needed.
                fused = graph_results
            elif strategy == "vector":
                fused = reciprocal_rank_fusion(
                    [semantic_results, keyword_results, title_results],
                    weights=[self.semantic_weight, self.keyword_weight, self.title_weight],
                    k=60,
                )
            else:  # hybrid
                if self.graph_retriever and graph_results:
                    fused = reciprocal_rank_fusion(
                        [semantic_results, keyword_results, title_results, graph_results],
                        weights=[
                            self.semantic_weight,
                            self.keyword_weight,
                            self.title_weight,
                            self.graph_weight,
                        ],
                        k=60,
                    )
                else:
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
            metrics_registry.observe(
                "rag_retrieval_latency_seconds",
                time.perf_counter() - started,
                labels={"strategy": strategy, "status": "success"},
            )
            metrics_registry.set_gauge(
                "rag_retrieval_results_count",
                len(final_results),
                labels={"strategy": strategy},
            )

            return final_results

        except Exception as e:
            logger.error("retrieval_failed", query=query, error=str(e))
            metrics_registry.observe(
                "rag_retrieval_latency_seconds",
                time.perf_counter() - started,
                labels={"strategy": strategy, "status": "error"},
            )
            metrics_registry.increment(
                "rag_retrieval_errors_total",
                labels={"strategy": strategy, "error_type": type(e).__name__},
            )
            raise RetrievalError(f"Retrieval failed: {e}")

    async def _semantic_search(
        self,
        query: str,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Vector similarity search."""
        try:
            started = time.perf_counter()
            self.fault_injector.maybe_raise("embedding")
            query_embedding = (await embed_texts_async([query]))[0]
            self.fault_injector.maybe_raise("milvus")
            results = await self.store.search_async(
                query_embedding=query_embedding,
                top_k=self.semantic_limit,
                expr=filter_expr,
            )
            self._record_path_metrics("semantic", started, len(results), "success")
            return results
        except Exception as e:
            logger.warning("semantic_search_failed", error=str(e))
            self._record_path_metrics("semantic", started, 0, "error")
            if _fault_component(e) == "milvus":
                raise
            return []

    async def _keyword_search(
        self,
        query: str,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Keyword/fulltext search on title and content."""
        try:
            started = time.perf_counter()
            self.fault_injector.maybe_raise("milvus")
            like_expr = build_like_expr(["title", "content"], query)
            if not like_expr:
                self._record_path_metrics("keyword", started, 0, "success")
                return []
            expr = combine_expr(like_expr, filter_expr)
            results = await self.store.query_async(
                expr=expr,
                output_fields=[
                    "title", "content", "source", "language", "category", "published_at",
                    "content_hash", "id", "user_id", "company_id", "url",
                ],
                limit=self.keyword_limit,
            )
            for r in results:
                r["score"] = 0.5
            self._record_path_metrics("keyword", started, len(results), "success")
            return results
        except Exception as e:
            logger.warning("keyword_search_failed", error=str(e))
            self._record_path_metrics("keyword", started, 0, "error")
            if _fault_component(e) == "milvus":
                raise
            return []

    async def _title_match(
        self,
        query: str,
        filter_expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """Exact title matching."""
        try:
            started = time.perf_counter()
            self.fault_injector.maybe_raise("milvus")
            like_expr = build_like_expr(["title"], query)
            if not like_expr:
                self._record_path_metrics("title", started, 0, "success")
                return []
            expr = combine_expr(like_expr, filter_expr)
            results = await self.store.query_async(
                expr=expr,
                output_fields=[
                    "title", "content", "source", "language", "category", "published_at",
                    "content_hash", "id", "user_id", "company_id", "url",
                ],
                limit=self.title_limit,
            )
            for r in results:
                r["score"] = 0.8
            self._record_path_metrics("title", started, len(results), "success")
            return results
        except Exception as e:
            logger.warning("title_match_failed", error=str(e))
            self._record_path_metrics("title", started, 0, "error")
            if _fault_component(e) == "milvus":
                raise
            return []

    async def _graph_search(self, query: str) -> list[dict[str, Any]]:
        """4th path: dual-level entity + relation search via Neo4j.

        Returned chunks carry the standard fields (chunk_id, content,
        title, url, source, score) plus graph-specific trace metadata
        (via_entities, via_relations) so downstream consumers (UI
        GraphPanel, agent answer generation) can show "this answer was
        reached via Apple --[invested_in]--> TSMC".

        Empty list when ``graph_retriever`` is None (graph layer not
        configured) or when the path fails — we never want a graph error
        to break the user-facing retrieval.
        """
        if self.graph_retriever is None:
            return []
        try:
            started = time.perf_counter()
            self.fault_injector.maybe_raise("graph")
            results = await self.graph_retriever.retrieve(query, top_k=self.graph_limit)
            self._record_path_metrics("graph", started, len(results), "success")
            return results
        except Exception as e:
            logger.warning("graph_search_failed", error=str(e), error_type=type(e).__name__)
            self._record_path_metrics("graph", started, 0, "error")
            reason = _fault_scenario(e) or type(e).__name__
            self.degradation_policy.decide(
                component="graph",
                failure=reason,
                requested_strategy="hybrid",
            )
            return []

    def _record_path_metrics(
        self,
        path: str,
        started: float,
        result_count: int,
        status: str,
    ) -> None:
        metrics_registry.observe(
            "rag_retrieval_path_latency_seconds",
            time.perf_counter() - started,
            labels={"path": path, "status": status},
        )
        metrics_registry.set_gauge(
            "rag_retrieval_path_results_count",
            result_count,
            labels={"path": path},
        )

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


def _fault_component(exc: Exception) -> str | None:
    component = getattr(exc, "component", None)
    return str(component) if component else None


def _fault_scenario(exc: Exception) -> str | None:
    scenario = getattr(exc, "scenario", None)
    return str(scenario) if scenario else None
