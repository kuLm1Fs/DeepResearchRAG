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


class Citation(BaseModel):
    claim: str
    source_indexes: list[int]
    support_level: str
    support_score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    trace_id: str
    citations: list[Citation] = Field(default_factory=list)


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


# --- 注册 ---
class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=256)
    password: str = Field(..., min_length=8, max_length=128)
    company_name: str | None = Field(None, max_length=256)  # 可选，不填则自动生成


class RegisterResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserResponse"


# --- 登录 ---
class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserResponse"


# --- Token 刷新 ---
class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- User 响应模型 ---
class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    company_id: str | None


# --- 通用错误 ---
class ErrorResponse(BaseModel):
    detail: str
