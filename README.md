# RAG News Intelligence

[English](README.en.md) | 简体中文

RAG News Intelligence 是一个面向新闻场景的双语 RAG 系统，支持中文/英文新闻采集、清洗、向量化、多路检索、LangGraph Agent 问答和来源引用。项目目标是在 4 核 / 15.6GB 级别服务器上稳定处理 10 万到 100 万篇新闻文章。

## 功能特性

- 多源新闻采集：RSS、HN API、Reddit API、HuggingFace 数据集和自定义爬虫。
- 双语内容处理：支持中文和英文新闻清洗、切块、检索与问答。
- 多路召回检索：语义向量检索、Milvus FULLTEXT 关键词检索、标题精确匹配。
- RRF 融合排序：默认 `k=60`，权重为 `0.5 / 0.3 / 0.2`。
- Agent 工作流：基于 LangGraph 编排查询分析、路由决策、结果评估、多源对比、答案生成和自反思。
- 可切换 LLM：DeepSeek 为主，OpenAI / Qwen 可作为 fallback，通过 `LLM_PROVIDER` 切换。
- 云端 Embedding：使用火山引擎 Embedding API，维度 1024，默认批量大小 50。
- 可观测性：请求级 `trace_id`、结构化日志、敏感信息脱敏、可控调试与缓存。
- 前后端一体：FastAPI SSE 流式接口 + React / Vite / Tailwind 前端。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.10+、FastAPI |
| Agent / RAG | LangChain、LangGraph |
| LLM | DeepSeek、OpenAI、Qwen |
| Embedding | 火山引擎 Embedding API |
| 向量数据库 | Milvus standalone + etcd + MinIO |
| 结构化存储 | PostgreSQL |
| 前端 | React、TypeScript、Vite、Tailwind CSS |

## 系统架构

```text
用户问题
  -> FastAPI SSE API
  -> LangGraph Agent
      -> 查询分析
      -> 路由决策
      -> 多路召回
          -> 语义向量检索
          -> 关键词全文检索
          -> 标题精确匹配
      -> RRF 融合排序
      -> 结果评估
      -> 多源对比
      -> 答案生成
      -> 自反思
  -> 带来源引用的流式回答
```

## 目录结构

```text
.
├── backend/                 # FastAPI、LangGraph Agent、检索、数据导入和评估
│   ├── src/
│   ├── scripts/
│   ├── tests/
│   ├── configs/.env.example
│   └── Makefile
├── frontend/                # React + TypeScript 前端
├── docker/                  # Milvus、etcd、MinIO、PostgreSQL
├── docs/                    # 设计文档、API 文档、数据库 schema
├── scripts/                 # 项目级脚本
└── README.en.md             # 英文 README
```

## 环境要求

- Python 3.10+
- Node.js 18+
- Docker / Docker Compose
- DeepSeek、OpenAI 或 Qwen API Key
- 火山引擎 Embedding API Key

## 快速启动

### 1. 启动基础服务

```bash
cd docker
docker compose up -d
docker compose ps
```

该命令会启动 Milvus、etcd、MinIO 和 PostgreSQL。

### 2. 初始化 PostgreSQL

```bash
cd docker
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -d rag_news < ../docs/schema.sql
```

如果数据库尚未创建，可以先执行：

```bash
cd docker
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -c "CREATE DATABASE rag_news;"
```

### 3. 配置并启动后端

```bash
cd backend
cp configs/.env.example configs/.env.dev
```

编辑 `backend/configs/.env.dev`，填入至少以下变量：

```bash
DEEPSEEK_API_KEY=sk-xxx
VOLCENGINE_API_KEY=xxx
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
```

安装依赖并启动开发服务：

```bash
make install
make dev
```

也可以直接使用 uv：

```bash
uv sync
uv run uvicorn src.api.app:app --reload
```

后端 API 文档默认位于 http://localhost:8000/docs。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务默认位于 http://localhost:5173。

## 数据导入与评估

导入 HuggingFace `ag_news` 示例数据：

```bash
cd backend
python scripts/seed_data.py
```

运行检索质量评估：

```bash
cd backend
python scripts/evaluate_retrieval.py
```

评估结果会输出到 `backend/data/eval_results/`，目标指标为 `Precision@5 >= 0.8`。

## 核心配置

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `ENV` | 运行环境 | `dev` |
| `DEBUG` | 是否启用调试模式 | `true` |
| `LLM_PROVIDER` | LLM 提供商：`deepseek`、`openai`、`qwen` | `deepseek` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `QWEN_API_KEY` | Qwen API Key | - |
| `VOLCENGINE_API_KEY` | 火山引擎 API Key | - |
| `MILVUS_HOST` | Milvus 主机 | `localhost` |
| `MILVUS_PORT` | Milvus 端口 | `19530` |
| `POSTGRES_HOST` | PostgreSQL 主机 | `localhost` |
| `POSTGRES_PORT` | PostgreSQL 端口 | `5432` |
| `LLM_CACHE` | 是否启用 LLM 响应缓存 | `true` |
| `PROMPT_VERSION` | Prompt 版本 | `v1` |

生产环境会强制关闭 `llm_cache`、`retrieval_dump` 和 `debug` 等调试能力。

## API

主要接口：

- `POST /api/query`：SSE 流式问答接口。
- `GET /api/stats`：数据与系统统计。
- 数据管理接口：用于文章导入、状态查看和检索调试。

更多细节见 `docs/api-docs.md`。

## 开发命令

后端：

```bash
cd backend
make install
make dev
make lint
uv run pytest
```

前端：

```bash
cd frontend
npm run dev
npm run build
```

基础服务：

```bash
cd docker
docker compose up -d
docker compose down
```

## Prompt 与缓存

Prompt 模板位于 `backend/src/agent/templates/`，按版本目录管理，例如 `v1/`、`v2/`，并可通过 `current` 软链接指向当前版本。运行时通过 `PROMPT_VERSION` 选择模板版本。

LLM 响应缓存位于 `backend/data/llm_cache/{version}/`，缓存 key 包含模型、Prompt 版本和输入内容，便于复现实验结果。

## 可观测性与安全

- 每个请求都会生成 `trace_id`，并通过 `X-Trace-ID` 响应头传播。
- 使用 structlog 输出结构化日志。
- 日志会自动脱敏 API Key 等敏感模式。
- 错误分为可忽略错误和关键错误：空检索等问题会记录后继续，Milvus 不可用或 API Key 无效等问题会中断请求。

## 许可证

如需开源发布，请在仓库中补充 LICENSE 文件。
