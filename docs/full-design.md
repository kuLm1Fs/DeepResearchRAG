# RAG News Intelligence — 完整版设计文档

## 1. 项目概述

构建一个中等规模（10万-100万条）的新闻资讯 RAG 系统，支持中英双语，覆盖多数据源采集、向量检索、Agent 智能问答。

### 1.1 核心目标

- 多源新闻数据自动采集与向量化
- 多路召回 + RRF 融合检索
- LangGraph Agent 智能问答，带来源引用
- 支持多维度过滤（时间/来源/语言/分类）
- 多源对比分析能力
- 增量数据更新

---

## 2. 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 后端框架 | Python + FastAPI | 异步高性能 API |
| RAG 框架 | LangChain + LangGraph | Agent 工作流编排 |
| LLM | DeepSeek API（主） + OpenAI（备） + Qwen（备） | 架构层抽象，配置切换 |
| Embedding | 火山引擎 Embedding API | 云端调用，不本地部署 |
| 向量数据库 | Milvus 全量版 | Docker Compose 部署（etcd + MinIO + milvus） |
| 前端 | React + TypeScript + Vite + Tailwind CSS | Clean Light 风格 |
| 基础设施 | Docker Compose | Milvus + etcd + MinIO |

### 2.1 服务器配置

- 4 核 2.6GHz CPU
- 15.6GB 内存
- 已安装 Docker
- 全部走 API，本地跑 Milvus + FastAPI，内存占用约 6-8GB

---

## 3. 项目结构

```
RAG/
├── backend/
│   ├── src/
│   │   ├── ingestion/              # 数据采集与处理
│   │   │   ├── base.py             # BaseCollector 抽象类
│   │   │   ├── rss_collector.py    # RSS 订阅源采集（中英文）
│   │   │   ├── hn_collector.py     # Hacker News API 采集器
│   │   │   ├── reddit_collector.py # Reddit API 采集器
│   │   │   ├── dataset_collector.py# HuggingFace 数据集加载器
│   │   │   ├── crawler.py          # 自定义爬虫（Scrapy/BS4）
│   │   │   ├── preprocessor.py     # 文本清洗、分块
│   │   │   └── pipeline.py         # 采集调度器
│   │   ├── vectorstore/
│   │   │   ├── milvus_store.py     # Milvus 连接与 CRUD
│   │   │   ├── schema.py           # Collection schema 定义
│   │   │   └── embedding.py        # 火山引擎 Embedding API 封装
│   │   ├── retrieval/
│   │   │   ├── retriever.py        # 多路召回（语义 + 关键词 + 标题匹配）
│   │   │   ├── fusion.py           # RRF 融合算法
│   │   │   └── filters.py          # 多维度过滤（时间/来源/语言）
│   │   ├── agent/
│   │   │   ├── graph.py            # LangGraph 工作流定义
│   │   │   ├── nodes.py            # 各节点实现
│   │   │   ├── state.py            # Agent 状态定义
│   │   │   └── templates/          # Prompt 模板（.txt 文件）
│   │   │       ├── analyze_query.txt
│   │   │       ├── generate_answer.txt
│   │   │       ├── evaluate_relevance.txt
│   │   │       ├── compare_sources.txt
│   │   │       └── self_reflect.txt
│   │   ├── llm/
│   │   │   ├── base.py             # LLM 抽象接口
│   │   │   ├── deepseek.py         # DeepSeek 客户端（主）
│   │   │   ├── openai.py           # OpenAI 客户端（备）
│   │   │   └── qwen.py            # Qwen 客户端（备）
│   │   ├── api/
│   │   │   ├── app.py              # FastAPI 应用 + 中间件
│   │   │   ├── routes/
│   │   │   │   ├── query.py        # 查询接口（SSE 流式）
│   │   │   │   ├── ingest.py       # 数据管理接口
│   │   │   │   └── admin.py        # 系统管理接口
│   │   │   └── models.py           # Pydantic 请求/响应模型
│   │   ├── core/
│   │   │   ├── config.py           # 配置管理（pydantic-settings）
│   │   │   ├── errors.py           # 错误分级定义
│   │   │   ├── logging.py          # 结构化日志配置
│   │   │   ├── middleware.py       # trace_id 中间件
│   │   │   └── cache.py           # LLM 缓存（按版本分目录）
│   │   └── cli/
│   │       └── main.py             # CLI 入口
│   ├── configs/
│   │   ├── rss_sources.yaml        # RSS 源列表配置
│   │   └── .env.example            # 环境变量模板
│   ├── data/
│   │   ├── llm_cache/              # LLM 响应缓存
│   │   │   └── v1/                 # 按版本分目录
│   │   └── eval_results/           # 检索质量评估结果
│   ├── tests/
│   ├── notebooks/                  # Jupyter 探索性分析
│   ├── scripts/
│   │   ├── evaluate_retrieval.py   # 检索质量评估脚本
│   │   ├── init_milvus.py          # 初始化 Milvus collection
│   │   └── seed_data.py            # 灌入种子数据
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx                 # 主界面（7:3 分栏）
│   │   ├── components/
│   │   │   ├── ChatWindow.tsx      # 对话窗口（流式显示）
│   │   │   ├── SourcePanel.tsx     # 来源面板（可折叠）
│   │   │   ├── SourceCard.tsx      # 来源卡片（折叠式）
│   │   │   ├── FilterBar.tsx       # 过滤栏
│   │   │   ├── CompareView.tsx     # 多源对比视图
│   │   │   └── Dashboard.tsx       # 数据概览仪表盘
│   │   ├── hooks/                  # 自定义 hooks
│   │   ├── api/                    # API 调用层
│   │   └── types/                  # TypeScript 类型
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── tsconfig.json
├── docker/
│   ├── docker-compose.yml          # Milvus + etcd + MinIO
│   └── docker-compose.dev.yml      # 开发环境覆盖
├── .env.dev                        # 开发环境配置
├── .env.prod                       # 生产环境配置
├── .gitignore
└── README.md
```

---

## 4. 数据采集方案

### 4.1 英文 RSS + API

| 数据源 | 方式 | 预估数据量 | 频率 |
|--------|------|-----------|------|
| Hacker News | 官方 API (free, no auth) | ~30万条/年 | 实时 |
| Reddit (r/worldnews, r/technology) | Reddit API (free tier) | ~10万条/天 | 每小时 |
| TechCrunch | RSS feed | ~20篇/天 | 每小时 |
| The Verge | RSS feed | ~30篇/天 | 每小时 |
| Ars Technica | RSS feed | ~20篇/天 | 每小时 |
| BBC News | RSS feed | ~50篇/天 | 每小时 |

RSS 采集器使用 `feedparser`，支持增量采集、错误重试。

### 4.2 中文 RSS + 网站

| 数据源 | 方式 | 预估数据量 | 频率 |
|--------|------|-----------|------|
| 36氪 | RSS + 爬虫 | ~30篇/天 | 每小时 |
| 少数派 | RSS feed | ~15篇/天 | 每小时 |
| InfoQ 中文站 | RSS feed | ~10篇/天 | 每小时 |
| 虎嗅 | RSS + 爬虫 | ~20篇/天 | 每小时 |
| IT 之家 | RSS feed | ~50篇/天 | 每小时 |

### 4.3 开源数据集

| 数据集 | 数据量 | 语言 | 字段 |
|--------|--------|------|------|
| AG News | 12万条 | 英文 | title, description, category |
| CNN/DailyMail | ~30万条 | 英文 | article, highlights |
| CLUESCQC | 中文问答数据 | 中文 | 问题、答案、上下文 |
| Multi-News | ~56K 文档集 | 英文 | 多文档+摘要 |

### 4.4 自定义爬虫

Scrapy 框架，遵守 robots.txt，1-3 秒间隔，支持 Cookie/UA 轮换。

**预估总数据量**: 初期 10-20 万条，持续采集可达 100 万+

---

## 5. 向量存储层

### 5.1 Embedding

- **服务**: 火山引擎 Embedding API
- **封装**: 统一 embed 函数，内部自动分批（batch_size=50）+ 重试（tenacity）
- **本地零占用**: 不加载任何模型

```python
import tenacity

@tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_exponential())
def embed_batch(texts: list[str], batch_size: int = 50) -> list[list[float]]:
    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        results.extend(volcengine_client.embed(batch))
    return results
```

### 5.2 Milvus Collection Schema

```
Collection: news_articles
├── id (INT64, primary key, auto_id)
├── embedding (FLOAT_VECTOR, dim=1024)
├── title (VARCHAR, max=512)
├── content (VARCHAR, max=8192)
├── summary (VARCHAR, max=1024)
├── source (VARCHAR, max=128)
├── url (VARCHAR, max=1024)
├── language (VARCHAR, max=10)             # zh / en
├── category (VARCHAR, max=64)
├── published_at (INT64)                   # 发布时间戳
├── collected_at (INT64)                   # 采集时间戳
├── content_hash (VARCHAR, max=64)         # SHA256，去重用
└── tags (JSON)

Index: IVF_FLAT on embedding, metric_type=COSINE, nlist=128
全文索引: VACHAR on title, content（Milvus 2.4+ FULLTEXT）
```

### 5.3 增量更新

1. 写入前计算 `content_hash`
2. 查询 Milvus 检查是否已存在
3. 不存在则插入，已存在则跳过
4. 定期全量重建索引（可选）

---

## 6. 召回层

### 6.1 多路召回 + RRF 融合

```python
# 路径 1: 语义召回
semantic_results = milvus.search(
    data=[query_embedding],
    limit=20,
    metric_type="COSINE"
)

# 路径 2: 关键词召回（Milvus 全文检索）
keyword_results = milvus.text_search(
    data=query_text,
    limit=20,
    output_fields=["title", "content"]
)

# 路径 3: 标题精确匹配
title_results = milvus.query(
    expr='title like "%{query}%"',
    limit=10
)

# RRF 融合
final = reciprocal_rank_fusion(
    [semantic_results, keyword_results, title_results],
    weights=[0.5, 0.3, 0.2]
)
```

RRF 公式: `score(d) = Σ 1/(k + rank_i(d))`，k=60

### 6.2 多维度过滤

- 时间范围: published_at 区间
- 来源: source 字段精确匹配
- 语言: language = "zh" / "en"
- 分类: category 分类过滤

### 6.3 排序

- MVP: 直接用向量相似度 top_k
- 完整版: 加 Re-ranker 精排（BAAI/bge-reranker-v2-m3，按需启用）

---

## 7. LangGraph Agent 工作流

### 7.1 完整工作流

```
                     ┌─────────────┐
                     │  用户查询    │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  查询分析    │  LLM 结构化输出意图、关键词、语言
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  路由决策    │  规则路由 + LLM 兜底
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
       ┌──────▼──────┐ ┌───▼────┐ ┌──────▼──────┐
       │ 语义检索     │ │混合检索 │ │ 过滤检索    │
       └──────┬──────┘ └───┬────┘ └──────┬──────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
                     ┌──────▼──────┐
                     │  结果评估    │  检查相关性、去重
                     └──────┬──────┘
                            │
                   ┌────────▼────────┐
                   │  结果足够？      │──No──▶ 扩展检索 ──┐
                   └────────┬────────┘                    │
                            │ Yes                         │
                     ┌──────▼──────┐                      │
                     │  多源对比    │  对比不同来源报道      │
                     └──────┬──────┘                      │
                            │                             │
                     ┌──────▼──────┐                      │
                     │  答案生成    │◀─────────────────────┘
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  自我反思    │  检查答案质量、引用准确性
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  最终输出    │  包含来源引用的答案
                     └─────────────┘
```

### 7.2 Agent State

```python
class AgentState(TypedDict):
    query: str                          # 用户原始查询
    trace_id: str                       # 请求追踪 ID
    parsed_query: ParsedQuery           # 解析后的结构化查询
    search_strategy: str                # 检索策略
    retrieval_results: list[Article]    # 检索结果
    filtered_results: list[Article]     # 过滤后结果
    answer: str                         # 生成的答案
    sources: list[Source]               # 引用来源
    reflection: Reflection              # 自我反思结果
    iteration: int                      # 当前迭代次数
```

### 7.3 路由策略

**完整版**: 规则路由为主，LLM 兜底

```python
def route(state: AgentState) -> str:
    intent = state["parsed_query"]

    # 规则路由
    if intent["intent"] == "comparison":
        return "multi_query_retrieve"
    elif intent["intent"] == "temporal":
        return "filtered_retrieve"
    elif intent["requires_multi_source"]:
        return "multi_source_retrieve"

    # 兜底: 标准多路召回
    return "direct_retrieve"
```

### 7.4 LLM 抽象层

```python
class BaseLLM(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message], **kwargs) -> str: ...

    @abstractmethod
    async def stream_chat(self, messages: list[Message], **kwargs) -> AsyncIterator[str]: ...

class DeepSeekLLM(BaseLLM): ...    # 主选
class OpenAILLM(BaseLLM): ...      # 备选
class QwenLLM(BaseLLM): ...        # 备选
```

通过 `.env` 配置切换：

```env
LLM_PROVIDER=deepseek        # 或 openai / qwen
LLM_MODEL=deepseek-chat      # 或 gpt-4o-mini / qwen-max
```

---

## 8. Prompt 管理

### 8.1 分离原则

Prompt 存放在 `src/agent/templates/` 目录，与代码分离：

```python
def load_prompt(name: str, **kwargs) -> str:
    template = (PROMPT_DIR / f"{name}.txt").read_text()
    return template.format(**kwargs)
```

### 8.2 版本化

```
src/agent/templates/
├── v1/
│   ├── generate_answer.txt
│   └── analyze_query.txt
├── v2/
│   ├── generate_answer.txt    # 优化后的版本
│   └── analyze_query.txt
└── current -> v2              # 软链接指向当前版本
```

通过环境变量切换: `PROMPT_VERSION=v2`

### 8.3 Prompt 调试

Debug 模式下记录完整 prompt 到日志：

```python
if settings.debug:
    logger.info("llm_prompt",
        prompt_name=name,
        prompt_content=prompt,
        prompt_length=len(prompt),
        variables={k: v[:100] for k, v in kwargs.items()}
    )
```

---

## 9. 可观测性与调试

### 9.1 环境隔离

```
.env.dev          # 本地开发，DEBUG=true，LLM 缓存开启
.env.prod         # 生产环境，DEBUG=false，所有 dump 禁用
```

生产环境自动关闭调试功能：

```python
if settings.is_prod:
    settings.llm_cache = False
    settings.retrieval_dump = False
    settings.log_level = "WARNING"
```

### 9.2 trace_id

每个请求生成唯一 trace_id，贯穿整个调用链路：

```python
@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:8])
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response
```

### 9.3 结构化日志

使用 structlog，每个节点输出结构化日志：

```python
logger.info("retrieval_started",
    trace_id=state["trace_id"],
    query=state["query"],
    strategy=state["search_strategy"]
)
```

### 9.4 LLM 缓存（按版本控制）

```python
# 缓存目录按版本组织
data/llm_cache/
├── v1/
│   ├── hash1.json
│   └── hash2.json
└── v2/
```

缓存 key 包含模型版本和 prompt 版本，换模型/换 prompt 时旧缓存自动失效。

### 9.5 检索质量评估

独立脚本，准备测试查询集，输出 Precision/Recall：

```bash
python scripts/evaluate_retrieval.py
# 输出: data/eval_results/2026-05-12.json
```

### 9.6 错误分级（MVP 简化为 2 级）

| 级别 | 处理方式 | 示例 |
|------|---------|------|
| 可忽略 | 记日志，继续执行 | 检索无结果、LLM 响应慢 |
| 需处理 | 抛异常，中断流程 | Milvus 挂了、API key 失效 |

### 9.7 敏感信息脱敏

日志中自动脱敏 API key：

```python
SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-***REDACTED***"),
    (re.compile(r"Bearer\s+\S+"), "Bearer ***REDACTED***"),
]
```

### 9.8 生产环境禁止全量 dump

启动时检查，`env=prod` 时强制关闭 `llm_cache`、`retrieval_dump`、`debug`。

---

## 10. API 设计

### 10.1 查询接口

```
POST /api/query
Body: {
    "query": "最近 AI 领域有什么重大进展？",
    "filters": {
        "language": "zh",
        "date_from": "2026-01-01",
        "sources": ["36kr", "techcrunch"]
    },
    "stream": true
}
Response: SSE 流式输出
```

### 10.2 数据管理接口

```
POST /api/ingest/trigger          # 触发数据采集
GET  /api/ingest/status           # 查看采集状态
GET  /api/stats                   # 数据统计
DELETE /api/articles/{id}         # 删除文章
```

### 10.3 系统管理接口

```
GET  /api/health                  # 健康检查
GET  /api/config                  # 查看当前配置
```

---

## 11. 前端设计

### 11.1 风格

- **设计风格**: Clean Light（Notion/Linear 风格）
- **配色**: #ffffff 底色 + #1a1a1a 文字 + #2563eb 蓝色强调 + #f8f9fa 卡片背景
- **技术**: React + TypeScript + Vite + Tailwind CSS

### 11.2 布局

左右分栏，对话区 70% + 来源面板 30%，来源面板可折叠。

```
┌──────────────────────────┬─────────────────────┐
│  对话区 (70%)             │  来源面板 (30%)      │
│                          │  [折叠/展开]         │
│  (对话流，支持流式显示)    │  检索到的文章卡片    │
│                          │  每次查询自动更新    │
├──────────────────────────┴─────────────────────┤
│  [输入你的问题...]                        [发送] │
└──────────────────────────────────────────────┘
```

### 11.3 来源卡片

折叠式：默认只显示标题和来源，鼠标悬停展开完整信息（时间、摘要、分类标签、相关度分数）。

---

## 12. 实现阶段

### Phase 1: 基础设施搭建
1. 初始化项目结构、pyproject.toml、依赖管理
2. Docker Compose 配置 Milvus + etcd + MinIO
3. 环境变量管理（.env.dev + .env.prod + pydantic-settings）
4. 配置管理模块
5. 结构化日志 + trace_id 中间件
6. LLM 缓存模块

### Phase 2: 数据采集层
1. BaseCollector 抽象类设计
2. RSS 采集器（中英文源）
3. Hacker News API 采集器
4. HuggingFace 数据集加载器
5. 自定义爬虫（Scrapy）
6. 文本预处理与分块
7. 采集调度 Pipeline

### Phase 3: 向量存储层
1. 火山引擎 Embedding API 封装（分批 + 重试）
2. Milvus Collection Schema 定义
3. 向量存储 CRUD 操作
4. 增量更新逻辑

### Phase 4: 召回层
1. 多路召回（语义 + 关键词 + 标题匹配）
2. RRF 融合算法
3. 多维度过滤
4. Re-ranker 集成（可选）

### Phase 5: Agent 与生成层
1. LangGraph State 定义
2. 各节点实现
3. LLM 抽象层（DeepSeek + OpenAI + Qwen）
4. Prompt 模板设计（.txt 分离）

### Phase 6: API 与 CLI
1. FastAPI 应用搭建
2. 查询接口（SSE 流式）
3. 数据管理接口
4. CLI 工具

### Phase 7: 前端 UI
1. React + TypeScript + Vite + Tailwind CSS 项目
2. 7:3 分栏布局
3. 对话窗口（流式显示）
4. 来源面板（可折叠 + 折叠式卡片）

---

## 13. 验证方案

1. **数据采集验证**: 逐个采集器测试，确认数据量和质量
2. **向量存储验证**: 写入/检索/过滤/增量更新各环节单独测试
3. **检索质量验证**: 跑 evaluate_retrieval.py，Precision@5 ≥ 0.8
4. **Agent 工作流验证**: 端到端测试查询 → 回答 → 引用的完整链路
5. **API 验证**: curl 测试所有接口
6. **前端验证**: 浏览器手动交互测试
7. **LangSmith tracing**: 每次运行自动记录，可视化排查
