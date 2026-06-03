from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results to return")
    language: str | None = Field(default=None, description="Filter by language (en/zh)")
    category: str | None = Field(default=None, description="Filter by category")
    stream: bool = Field(default=True, description="Enable SSE streaming")
    date_from: int | None = Field(default=None, description="Filter published_at >= (epoch seconds)")
    date_to: int | None = Field(default=None, description="Filter published_at <= (epoch seconds)")


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
    total_chunks: int
    sources: dict[str, int]
    categories: dict[str, int]
    languages: dict[str, int]


class HealthResponse(BaseModel):
    status: str
    milvus_connected: bool
    postgres_connected: bool = False
    llm_provider: str


# --- Phase 5: graph introspection API ---
class GraphEntityRef(BaseModel):
    entity_id: str
    name: str
    type: str | None = None
    mention_count: int | None = None


class GraphRelationRef(BaseModel):
    type: str
    target_id: str
    target_name: str
    target_type: str | None = None
    weight: float | None = None
    description: str | None = None


class GraphEntitySubgraph(BaseModel):
    entity_id: str
    name: str
    type: str | None
    description: str | None
    mention_count: int | None
    relations: list[GraphRelationRef] = Field(default_factory=list)
    sample_chunks: list[dict] = Field(default_factory=list)


class GraphChunkEntity(BaseModel):
    entity_id: str
    name: str
    type: str | None
    relations: list[dict] = Field(default_factory=list)


class GraphStatsResponse(BaseModel):
    enabled: bool
    counts: dict[str, int] = Field(default_factory=dict)
    top_entities: list[GraphEntityRef] = Field(default_factory=list)


class GraphRebuildResponse(BaseModel):
    status: str
    message: str
    task_id: str | None = None


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


class SSEGraphFactsEvent(BaseModel):
    """Emitted once per /api/query request, after sources, so the frontend
    can prep the graph panel before the answer streams. ``data`` shape::

        {
          "entities": [{"entity_id", "name", "type"}, ...],
          "relations": [{"source", "target", "type"}, ...],
          "strategy": "hybrid" | "vector" | "graph",
          "strategy_reason": "...",
          "highlighted_entity_ids": [...]   # chunk_id -> entity_ids mapping
        }
    """

    type: str = "graph_facts"
    data: dict


# Ingest endpoint models
class IngestTriggerRequest(BaseModel):
    source: str | None = Field(default=None, description="Specific collector name, None for all")
    limit: int | None = Field(default=None, description="Limit number of articles to collect")
    fetch_full_text: bool = Field(default=True, description="Use trafilatura to fetch full article text")
    index: bool = Field(default=True, description="Embed and insert collected articles into Milvus")
    build_graph: bool = Field(
        default=True,
        description="Build / extend the knowledge graph in Neo4j after Milvus insert. "
        "Honors GRAPH_ENABLED env var; failures are isolated and do not roll back the vector write.",
    )


class IngestTriggerResponse(BaseModel):
    status: str
    source: str | None
    message: str
    task_id: str | None = None
    articles_collected: int = 0
    chunks_indexed: int = 0
    records_inserted: int = 0
    graph_entities: int = 0
    graph_relations: int = 0
    graph_skipped: int = 0
    graph_errors: int = 0


class IngestTaskResponse(BaseModel):
    task_id: str
    status: str  # pending | running | completed | failed
    source: str | None
    articles_collected: int = 0
    chunks_indexed: int = 0
    records_inserted: int = 0
    graph_entities: int = 0
    graph_relations: int = 0
    graph_skipped: int = 0
    graph_errors: int = 0
    error: str | None = None


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


# --- Feedback ---
class FeedbackRequest(BaseModel):
    query_id: str | None = Field(default=None, description="Trace ID of the query")
    query_text: str | None = Field(default=None, max_length=2048)
    rating: str = Field(..., pattern="^(positive|negative)$")
    reason: str | None = Field(default=None, max_length=64, description="e.g. irrelevant, outdated, wrong, incomplete")
    comment: str | None = Field(default=None, max_length=1024)


class FeedbackResponse(BaseModel):
    id: int
    message: str = "Feedback recorded"


class FeedbackStatsResponse(BaseModel):
    total: int
    positive: int
    negative: int
    satisfaction_rate: float
    top_negative_reasons: dict[str, int]
