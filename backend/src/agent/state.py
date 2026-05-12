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
    reflection: dict[str, Any]           # Self-reflection result
    iteration: int                      # Current iteration count
    error: str | None                    # Error message if any