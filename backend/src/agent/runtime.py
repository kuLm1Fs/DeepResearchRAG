from dataclasses import dataclass, field
from typing import Any

from core import settings


@dataclass
class NodePolicy:
    """Execution policy for a graph node."""

    error_level: str = "critical"
    timeout_seconds: float | None = None
    fallback_result: dict[str, Any] | None = None


@dataclass
class AgentRuntime:
    """Runtime dependencies for agent nodes.

    Keeping provider construction behind this object lets tests and production
    callers inject LLM/retrieval implementations without patching module globals.
    """

    config: Any = field(default_factory=lambda: settings)
    node_policies: dict[str, NodePolicy] = field(default_factory=dict)

    def create_llm(self):
        from llm import create_llm

        return create_llm(
            provider=self.config.llm_provider,
            api_key=getattr(self.config, f"{self.config.llm_provider}_api_key"),
            model=self.config.llm_model,
        )

    def create_retriever(self):
        from retrieval import MultiPathRetriever
        from vectorstore import MilvusStore

        graph_retriever = self.create_graph_retriever()
        return MultiPathRetriever(
            MilvusStore(),
            graph_retriever=graph_retriever,
        )

    def create_graph_retriever(self):
        """Build a GraphRetriever wired to a Neo4j connection, or None if
        graph is disabled / Neo4j is unreachable.

        Returning None lets MultiPathRetriever degrade gracefully: hybrid
        and vector strategies still work with just the 3 Milvus paths.
        We swallow connection errors here so a flaky Neo4j during boot
        doesn't take down the whole agent — vector-only mode is the
        fallback.
        """
        if not getattr(self.config, "graph_enabled", True):
            return None
        try:
            # Same dual-spelling tolerance trick as _build_entity_vocabulary
            # in nodes.py — pytest test ordering occasionally leaves only
            # the ``src.graph.X`` keys in sys.modules.
            try:
                from graph.neo4j_store import Neo4jStore
                from graph.builder import build_graph_for_articles  # noqa: F401 - cache for indexer
            except ModuleNotFoundError:
                from src.graph.neo4j_store import Neo4jStore
            from retrieval.graph_retriever import GraphRetriever

            store = Neo4jStore(
                uri=self.config.neo4j_uri,
                user=self.config.neo4j_user,
                password=self.config.neo4j_password,
                database=self.config.neo4j_database,
            )
            return GraphRetriever(store)
        except Exception as exc:  # noqa: BLE001 - degrade, don't crash boot
            import logging
            logging.getLogger(__name__).warning(
                "graph_retriever_init_failed_falling_back_to_vector",
                extra={"error": str(exc), "error_type": type(exc).__name__},
            )
            return None

    def with_answer_cache(self, llm):
        cache_enabled = getattr(self.config, "llm_cache_enabled", self.config.llm_cache)
        if not cache_enabled:
            return llm

        from llm.cache import CachedLLM

        return CachedLLM(
            llm,
            cache_dir=self.config.llm_cache_dir / self.config.llm_provider,
        )

    def policy_for(self, node_name: str) -> NodePolicy:
        return self.node_policies.get(node_name, NodePolicy())

    def trace_metrics(self, node_name: str, output: dict[str, Any]) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "approx_output_tokens": _approx_tokens(output),
        }

        for key in ("retrieval_results", "filtered_results", "sources"):
            if isinstance(output.get(key), list):
                metrics[f"{key}_count"] = len(output[key])

        if isinstance(output.get("answer"), str):
            metrics["answer_chars"] = len(output["answer"])

        answer_reflection = output.get("answer_reflection")
        if isinstance(answer_reflection, dict):
            unsupported = answer_reflection.get("unsupported_claims", [])
            metrics["unsupported_claims_count"] = len(unsupported)

        if isinstance(output.get("citations"), list):
            metrics["citations_count"] = len(output["citations"])
            metrics["unsupported_citations_count"] = sum(
                1 for item in output["citations"]
                if item.get("support_level") == "unsupported"
            )

        return metrics


def _approx_tokens(value: Any) -> int:
    text = str(value)
    return max(1, len(text) // 4) if text else 0
