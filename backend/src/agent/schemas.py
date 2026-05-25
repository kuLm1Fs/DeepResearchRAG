from typing import Literal

from pydantic import BaseModel, Field


class QueryAnalysis(BaseModel):
    intent: Literal["factual", "analysis", "comparison", "summary"] = "factual"
    rewritten_query: str = Field(min_length=1)
    sub_queries: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class RetrievalEvaluation(BaseModel):
    relevance: Literal["HIGH", "MEDIUM", "LOW"]
    coverage: int = Field(ge=0, le=100)
    gaps: list[str] = Field(default_factory=list)
    action: Literal["proceed", "re_search", "expand"]
    re_search_query: str = ""
