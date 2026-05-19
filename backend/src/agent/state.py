from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """LangGraph agent state for RAG pipeline."""

    query: str                          # User's original query
    trace_id: str                       # Request trace ID
    parsed_query: dict[str, Any]        # LLM-parsed query (intent, keywords, language)
    search_strategy: str                # Selected retrieval strategy
    retrieval_results: list[dict]        # Raw retrieval results
    filtered_results: list[dict]         # Filtered results
    answer: str                          # Generated answer
    sources: list[dict]                  # Source citations
    citations: list[dict]                # Claim-to-source citation bindings
    retrieval_evaluation: dict[str, Any] # Retrieval relevance and re-search decision
    answer_reflection: dict[str, Any]    # Answer quality self-reflection result
    reflection: dict[str, Any]           # Backward-compatible retrieval evaluation alias
    iteration: int                      # Current iteration count
    top_k: int                          # Number of results to retrieve
    error: str | None                    # Error message if any
    conversation_history: list[dict]    # Dialog history, each item is {"role": "user"/"assistant", "content": str}
    use_history: bool                   # Whether to use history context (default False)
    search_plan: dict[str, Any]          # Planned retrieval queries and limits
    search_queries: list[str]            # Query rewrites/sub-queries used for retrieval
    source_comparison: dict[str, Any] | None  # Multi-source comparison summary
    re_search_count: int                 # Number of supplemental retrieval attempts
    runtime: Any                         # Optional injected runtime dependencies
    node_traces: list[dict[str, Any]]    # Per-node execution trace summaries
