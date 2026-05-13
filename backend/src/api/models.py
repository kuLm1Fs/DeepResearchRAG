from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results to return")
    language: str | None = Field(default=None, description="Filter by language (en/zh)")
    category: str | None = Field(default=None, description="Filter by category")
    stream: bool = Field(default=True, description="Enable SSE streaming")


class Source(BaseModel):
    title: str
    content: str
    source: str
    category: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    trace_id: str


class StatsResponse(BaseModel):
    total_articles: int
    sources: dict[str, int]
    categories: dict[str, int]
    languages: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    milvus_connected: bool
    llm_provider: str


# SSE Event types
class SSETokenEvent(BaseModel):
    type: str = "token"
    data: str


class SSESourcesEvent(BaseModel):
    type: str = "sources"
    data: list[Source]


class SSEDoneEvent(BaseModel):
    type: str = "done"
    data: QueryResponse


class SSEErrorEvent(BaseModel):
    type: str = "error"
    data: str


# Ingest endpoint models
class IngestTriggerRequest(BaseModel):
    source: str | None = Field(default=None, description="Specific collector name, None for all")
    limit: int | None = Field(default=None, description="Limit number of articles to collect")


class IngestTriggerResponse(BaseModel):
    status: str
    source: str | None
    message: str
    articles_collected: int = 0


class IngestStatusResponse(BaseModel):
    total_articles: int
    sources: dict[str, int]
    collectors: list[str]