# RAG News Intelligence — MVP 设计文档

## 1. MVP 目标

用最小的代码量跑通完整的 RAG pipeline：**数据采集 → 向量化存储 → 智能问答 → Web 展示**。

### 1.1 MVP 范围

| 层 | 包含 | 不包含（后续迭代） |
|----|------|-------------------|
| 数据源 | HuggingFace ag_news 数据集 | RSS、爬虫、API |
| 向量库 | Milvus 全量版（Docker） | — |
| 召回 | 多路召回 + RRF 融合 | Re-ranker |
| Agent | 精简 4 节点工作流 | 多策略路由、自我反思 |
| LLM | DeepSeek API | OpenAI、Qwen |
| API | 查询 + 统计 2 个接口 | 数据管理、系统管理 |
| 前端 | 对话 + 来源面板 | 过滤、对比、仪表盘 |

---

## 2. 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 后端 | Python + FastAPI | 最小化 API |
| RAG | LangChain + LangGraph | Agent 核心 |
| LLM | DeepSeek API | 兼容 OpenAI SDK |
| Embedding | 火山引擎 Embedding API | 云端调用，不本地部署 |
| 向量库 | Milvus 全量版 | Docker Compose 部署 |
| 前端 | React + TypeScript + Vite + Tailwind CSS | Clean Light 风格 |

---

## 3. 项目结构（MVP）

```
RAG/
├── backend/
│   ├── src/
│   │   ├── ingestion/
│   │   │   ├── dataset_loader.py   # HuggingFace 数据集加载
│   │   │   ├── preprocessor.py     # 文本清洗 + 分块
│   │   │   └── pipeline.py         # 采集→向量化→存储
│   │   ├── vectorstore/
│   │   │   ├── store.py            # Milvus 连接 + CRUD
│   │   │   ├── schema.py           # Collection 定义
│   │   │   └── embedding.py        # 火山引擎 API 封装
│   │   ├── retrieval/
│   │   │   ├── retriever.py        # 多路召回
│   │   │   └── fusion.py           # RRF 融合
│   │   ├── agent/
│   │   │   ├── graph.py            # LangGraph 工作流（精简版）
│   │   │   ├── nodes.py            # 节点实现
│   │   │   └── templates/
│   │   │       ├── generate_answer.txt
│   │   │       └── evaluate_relevance.txt
│   │   ├── llm/
│   │   │   └── client.py           # DeepSeek 客户端 + 缓存
│   │   └── api/
│   │       ├── app.py              # FastAPI + trace_id 中间件
│   │       └── models.py           # 请求/响应模型
│   ├── configs/
│   │   └── .env.example
│   ├── data/
│   │   ├── llm_cache/v1/           # LLM 响应缓存
│   │   └── eval_results/           # 检索评估结果
│   ├── scripts/
│   │   ├── evaluate_retrieval.py   # 检索质量评估
│   │   └── seed_data.py            # 灌入数据
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx                 # 7:3 分栏主界面
│   │   ├── components/
│   │   │   ├── ChatWindow.tsx      # 对话窗口（流式）
│   │   │   ├── SourcePanel.tsx     # 来源面板（可折叠）
│   │   │   └── SourceCard.tsx      # 来源卡片（折叠式）
│   │   └── api/
│   │       └── client.ts           # API 调用
│   ├── package.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── tsconfig.json
├── docker/
│   └── docker-compose.yml          # Milvus + etcd + MinIO
├── .env.dev
├── .env.prod
├── .gitignore
└── README.md
```

---

## 4. MVP 数据源

### 4.1 唯一数据源: HuggingFace AG News

```python
from datasets import load_dataset

dataset = load_dataset("fancyzhx/ag_news", split="train[:10000]")
```

字段结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| text | string | 新闻标题 + 描述 |
| label | int | 0=World, 1=Sports, 2=Business, 3=Sci/Tech |

### 4.2 数据处理流程

```
ag_news 原始数据
    │
    ▼
文本清洗（去 HTML、统一编码）
    │
    ▼
分块（RecursiveCharacterTextSplitter, chunk_size=500）
    │
    ▼
火山引擎 Embedding API 向量化（dim=1024，批量调用）
    │
    ▼
写入 Milvus
```

### 4.3 数据量

- MVP 灌入: **1 万条**（约 3-5 分钟完成）
- 后续可扩展到: 12 万条全量

---

## 5. Milvus Schema

```
Collection: news_articles
├── id (INT64, primary key, auto_id)
├── embedding (FLOAT_VECTOR, dim=1024)
├── title (VARCHAR, max=512)
├── content (VARCHAR, max=4096)
├── source (VARCHAR, max=64)         # "ag_news"
├── language (VARCHAR, max=10)       # "en"
├── category (VARCHAR, max=32)       # "World"/"Sports"/"Business"/"Sci-Tech"
└── published_at (INT64)             # 时间戳

Index: IVF_FLAT on embedding, metric_type=COSINE, nlist=128
全文索引: VACHAR on title, content（用于关键词召回）
```

---

## 6. 多路召回 + RRF

MVP 即采用多路召回，不走单路语义：

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

---

## 7. LangGraph Agent（精简版）

### 7.1 工作流

```
用户查询
    │
    ▼
┌──────────┐
│ 向量检索  │  多路召回 + RRF，top_k=5
└────┬─────┘
     │
     ▼
┌──────────┐     无相关结果
│ 结果评估  │ ──────────▶ 扩展检索（扩大 top_k）
└────┬─────┘
     │ 有相关结果
     ▼
┌──────────┐
│ 答案生成  │  LLM 基于检索结果生成回答 + 引用
└────┬─────┘
     │
     ▼
┌──────────┐
│ 自我反思  │  检查答案质量，不合格则重新生成
└──────────┘
```

### 7.2 与完整版的差异

| 能力 | MVP | 完整版 |
|------|-----|--------|
| 查询分析 | 不做 | LLM 结构化输出 |
| 检索策略 | 多路召回 + RRF | + 多维度过滤 |
| 路由决策 | 不做，直接检索 | 规则路由 + LLM 兜底 |
| 结果评估 | 简单相关性判断 | 相关性打分 + 去重 |
| 多源对比 | 无 | 对比不同来源报道 |
| 自我反思 | 基础反思 | 深度反思 + 引用准确性 |
| 迭代检索 | 扩展 top_k | 改变检索策略 |

### 7.3 Agent State（MVP）

```python
class AgentState(TypedDict):
    query: str                      # 用户原始查询
    trace_id: str                   # 请求追踪 ID
    retrieval_results: list[dict]   # 检索结果
    answer: str                     # 生成的答案
    sources: list[dict]             # 引用来源列表
    iteration: int                  # 当前迭代次数
```

---

## 8. LLM 集成

### 8.1 DeepSeek API

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": prompt}]
)
```

### 8.2 LLM 缓存

调试阶段缓存 LLM 响应，避免重复调用：

```python
class CachedLLM:
    def __init__(self, client, cache_dir="data/llm_cache/v1"):
        ...

    async def chat(self, messages, **kwargs):
        cache_key = hash(str(messages) + str(kwargs))
        cache_path = f"{self.cache_dir}/{cache_key}.json"
        if os.path.exists(cache_path) and settings.llm_cache:
            return json.load(open(cache_path))["response"]
        response = await self.client.chat(messages, **kwargs)
        json.dump({"messages": messages, "response": response}, open(cache_path, "w"))
        return response
```

### 8.3 配置

```env
# .env.dev
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-xxx
VOLCENGINE_API_KEY=xxx
LLM_CACHE=true
DEBUG=true
LOG_LEVEL=DEBUG
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

---

## 9. API 设计

### 9.1 查询接口

```
POST /api/query
Request:
{
    "query": "What are the latest developments in AI?",
    "top_k": 5,
    "language": "en"
}

Response (SSE stream):
data: {"type": "sources", "data": [...]}
data: {"type": "token", "data": "The"}
data: {"type": "token", "data": " latest"}
...
data: {"type": "done", "data": {"answer": "...", "sources": [...]}}
```

### 9.2 统计接口

```
GET /api/stats

Response:
{
    "total_articles": 10000,
    "sources": {"ag_news": 10000},
    "categories": {"World": 2500, "Sports": 2500, ...},
    "languages": {"en": 10000}
}
```

---

## 10. 前端设计

### 10.1 风格与布局

- **风格**: Clean Light（Notion/Linear 风格）
- **配色**: #ffffff 底 + #1a1a1a 文字 + #2563eb 蓝色强调 + #f8f9fa 卡片
- **布局**: 对话 70% + 来源面板 30%（可折叠）
- **技术**: React + TypeScript + Vite + Tailwind CSS

### 10.2 页面结构

```
┌──────────────────────────┬─────────────────────┐
│  对话区 (70%)             │  来源面板 (30%)      │
│                          │  [折叠/展开]         │
│  🤖 根据检索到的新闻...   │  📰 来源 1           │
│                          │  📰 来源 2           │
│  (流式逐字显示)           │  📰 来源 3           │
│                          │                     │
├──────────────────────────┴─────────────────────┤
│  [输入你的问题...]                        [发送] │
└──────────────────────────────────────────────┘
```

### 10.3 来源卡片

折叠式：默认只显示标题和来源，鼠标悬悬展开时间、摘要、分类标签、相关度分数。

---

## 11. 实现步骤（5 步）

### Step 1: 项目骨架 + 基础设施
- 创建 backend 目录，pyproject.toml，依赖管理
- 创建 frontend 目录，Vite React TS + Tailwind CSS
- Docker Compose 配置 Milvus + etcd + MinIO
- 火山引擎 Embedding API 封装
- .env.dev 配置管理
- trace_id 中间件 + 结构化日志
- **验证**: Milvus 容器启动，Embedding API 调用成功

### Step 2: 数据采集 + 向量化 + 存储
- HuggingFace ag_news 数据集加载
- 文本预处理 + 分块
- 火山引擎 API 批量向量化
- 写入 Milvus
- **验证**: 脚本灌入 1 万条数据，确认可检索

### Step 3: 多路召回 + LangGraph Agent
- 多路召回（语义 + 关键词 + 标题匹配）
- RRF 融合
- DeepSeek API 集成 + LLM 缓存
- LangGraph 4 节点工作流
- **验证**: CLI 输入问题，返回带来源引用的答案

### Step 4: FastAPI 接口
- `POST /api/query`（SSE 流式）
- `GET /api/stats`
- CORS 配置
- **验证**: curl 测试返回正确 JSON

### Step 5: React 前端
- 7:3 分栏布局
- 对话窗口（流式显示）
- 来源面板（可折叠 + 折叠式卡片）
- **验证**: 浏览器完整查询流程

---

## 12. 关键依赖

```toml
# backend/pyproject.toml
[project]
dependencies = [
    "langchain>=0.3",
    "langchain-community>=0.3",
    "langgraph>=0.2",
    "pymilvus>=2.4",
    "datasets>=2.20",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "openai>=1.0",
    "python-dotenv>=1.0",
    "pydantic-settings>=2.0",
    "structlog>=24.0",
    "tenacity>=8.0",
]
```

```json
// frontend/package.json
{
  "dependencies": {
    "react": "^18.3",
    "react-dom": "^18.3"
  },
  "devDependencies": {
    "@types/react": "^18.3",
    "@vitejs/plugin-react": "^4.3",
    "typescript": "^5.5",
    "vite": "^5.4",
    "tailwindcss": "^3.4",
    "postcss": "^8.4",
    "autoprefixer": "^10.4"
  }
}
```

---

## 13. 验证清单

| # | 验证项 | 通过标准 |
|---|--------|---------|
| 1 | Milvus Docker 启动 | `docker ps` 显示 milvus-standalone 容器运行中 |
| 2 | Embedding API 调用 | 火山引擎 API 返回正确维度向量 |
| 3 | 数据灌入 1 万条 | Milvus collection num_entities == 10000 |
| 4 | 多路召回 | 语义+关键词+标题三路都有结果 |
| 5 | RRF 融合 | 融合后排序合理，相关文档排在前面 |
| 6 | Agent 端到端 | CLI 输入问题 → 带引用的答案 |
| 7 | LLM 缓存 | 第二次相同查询不调 API |
| 8 | FastAPI 接口 | curl 返回 200 + 正确 JSON |
| 9 | SSE 流式输出 | 浏览器逐字显示答案 |
| 10 | React 前端 | 7:3 分栏，对话+来源面板正常 |
| 11 | 来源卡片 | 悬停展开详情 |
| 12 | trace_id | 响应头包含 X-Trace-ID |
| 13 | 数据统计 | `/api/stats` 返回正确数量 |
