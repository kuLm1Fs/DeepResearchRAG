from typing import Literal

from pydantic import BaseModel, Field


class QueryAnalysis(BaseModel):
    intent: Literal["factual", "analysis", "comparison", "summary"] = "factual"
    rewritten_query: str = Field(min_length=1)
    sub_queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    # GraphRAG routing — populated by ``apply_routing_rules`` after the LLM
    # returns. ``retrieval_strategy`` decides which paths MultiPathRetriever
    # runs; ``strategy_reason`` is for debug/observability. The LLM may
    # suggest a strategy in its response but rules in nodes.py have final
    # say (the LLM tends to over-prefer "graph" once it knows the option
    # exists).
    retrieval_strategy: Literal["vector", "graph", "hybrid"] = "hybrid"
    strategy_reason: str = ""


class RetrievalEvaluation(BaseModel):
    relevance: Literal["HIGH", "MEDIUM", "LOW"]
    coverage: int = Field(ge=0, le=100)
    gaps: list[str] = Field(default_factory=list)
    action: Literal["proceed", "re_search", "expand"]
    re_search_query: str = ""
