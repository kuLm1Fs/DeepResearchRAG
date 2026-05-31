# RAG Finance Intelligence

[English](README.en.md) | 简体中文

面向金融场景的双语 RAG 系统，支持中英文金融资讯采集、向量化、多路检索、LangGraph Agent 问答和来源引用。目标是在 4 核 / 15.6GB 服务器上稳定处理 10 万到 100 万篇金融文档。

## 功能特性

### 数据采集与处理
- 多源金融数据采集：财经 RSS、SEC 公告、金融新闻 API、HuggingFace 金融数据集
- 双语内容处理：中英文清洗、切块（RecursiveCharacterTextSplitter, chunk_size=500）、检索与问答
- 云端 Embedding：火山引擎 API，维度 1024，批量大小 50，自动重试
- 增量去重：基于 content_hash（SHA256）的 Milvus 增量写入

### 检索与生成
- 多路召回：语义向量检索（COSINE）、Milvus FULLTEXT 关键词检索、标题精确匹配
- RRF 融合排序：`k=60`，权重 `0.5 / 0.3 / 0.2`
- 时间衰减加权：基于 `published_at` 的指数衰减（半衰期可配置）
- 日期范围过滤：查询时可指定 `date_from` / `date_to` 时间窗口
- LangGraph Agent 工作流：查询分析 → 路由决策 → 多路召回 → 结果评估 → 多源对比 → 答案生成 → 自反思
- 可切换 LLM：DeepSeek 为主，OpenAI / Qwen 可通过 `LLM_PROVIDER` 切换

### Deep Research
- 五阶段研究流水线：Planner → Retriever → Analyst → Checker → Writer
- 自动补充检索：Checker 发现缺口时自动回退到 Retriever（最多 20 次工具调用）
- 质量报告：证据覆盖率、来源多样性、新鲜度、可信度问题、缺口与冲突检测
- PPT 大纲生成：自动从研究报告提取幻灯片大纲
- 实时进度：SSE 流式推送当前步骤、执行日志和中间结果
- 任务取消：支持运行中取消研究任务

### 平台能力
- JWT 认证：注册、登录、Token 刷新，支持多设备并发
- 多租户：基于 company_id 的数据隔离和配额管理
- 审计日志：关键操作（查询、导入、研究）自动记录
- 请求级可观测性：`trace_id` 全链路传播、structlog 结构化日志、敏感信息脱敏
- 前后端一体：FastAPI SSE 流式接口 + React / Vite / Tailwind 前端
- 在线反馈：用户满意度追踪（thumbs up/down + 原因标签）

### 评估体系
- 检索质量：Precision@K, Recall@K, NDCG@K（K=1,3,5,10）
- 端到端评估：LLM-as-Judge（Faithfulness + Relevance 1-5 分）
- 引用覆盖率：每条 claim 是否有 supported citation
- 按难度分层分析：easy / medium / hard 查询分别统计

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.10+, FastAPI |
| Agent / RAG | LangChain, LangGraph |
| LLM | DeepSeek, OpenAI, Qwen |
| Embedding | 火山引擎 Embedding API |
| 向量数据库 | Milvus standalone + etcd + MinIO |
| 结构化存储 | PostgreSQL |
| 前端 | React, TypeScript, Vite, Tailwind CSS |
| 部署 | Docker / Docker Compose |

## 系统架构

```text
用户问题
  -> FastAPI SSE API（JWT 认证 + trace_id）
  -> LangGraph Agent
      -> 查询分析（LLM 结构化输出）
      -> 路由决策（规则 + LLM fallback）
      -> 多路召回
          -> 语义向量检索（COSINE）
          -> 关键词全文检索（FULLTEXT）
          -> 标题精确匹配
      -> RRF 融合排序
      -> 时间衰减加权
      -> 结果评估
      -> 多源对比
      -> 答案生成（LLM）
      -> 自反思 + 引用绑定
  -> 带来源引用的流式回答
```

Deep Research 流程：

```text
用户研究问题
  -> POST /api/research（创建异步任务）
  -> Planner（拆解子问题）
  -> Retriever（多路检索）
  -> Analyst（提取论点）
  -> Checker（验证 + 缺口检测）
      -> 有缺口？回退 Retriever（最多 N 轮）
  -> Writer（生成报告 + PPT 大纲）
  -> SSE 实时推送进度
```

## 目录结构

```text
.
├── backend/                    # FastAPI 后端
│   ├── src/
│   │   ├── api/                # 路由、认证、模型
│   │   ├── agent/              # LangGraph Agent、Deep Research
│   │   ├── auth/               # JWT 认证
│   │   ├── core/               # 日志、审计、限流、配置
│   │   ├── db/                 # PostgreSQL 连接与模型
│   │   ├── eval/               # LLM-as-Judge 评估模块
│   │   ├── ingestion/          # 数据采集器（RSS、HN、HuggingFace）
│   │   ├── llm/                # LLM 抽象层
│   │   ├── retrieval/          # 多路召回、融合、重排序
│   │   └── vectorstore/        # Milvus 存储、Embedding
│   ├── scripts/                # 数据导入、评估脚本
│   ├── data/                   # 评测集、评估结果
│   ├── tests/                  # pytest 测试套件
│   ├── migrations/             # SQL 迁移
│   └── Dockerfile
├── frontend/                   # React + TypeScript 前端
│   ├── src/
│   │   ├── components/         # ChatWindow, ResearchPanel, IngestPanel 等
│   │   ├── api/                # API 客户端（token 刷新、错误处理）
│   │   └── types/              # TypeScript 类型定义
│   └── Dockerfile
├── docker/                     # Docker Compose 基础设施
├── docs/                       # 设计文档、部署文档
└── .github/                    # CI/CD 工作流
```

## 快速启动

### 1. 启动基础服务

```bash
cd docker
docker compose up -d
```

启动 Milvus、etcd、MinIO 和 PostgreSQL。

### 2. 初始化数据库

```bash
cd docker
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -c "CREATE DATABASE rag_news;"
docker exec -i $(docker compose ps -q postgres) \
  psql -U rag_user -d rag_news < ../docs/schema.sql
```

### 3. 配置后端

```bash
cd backend
cp configs/.env.example configs/.env.dev
```

编辑 `configs/.env.dev`，至少填入：

```bash
DEEPSEEK_API_KEY=sk-xxx
VOLCENGINE_API_KEY=xxx
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
```

### 4. 启动后端

```bash
cd backend
make install
make dev
```

或使用 uv：

```bash
uv sync
uv run uvicorn src.api.app:app --reload --app-dir src
```

API 文档：http://localhost:8000/docs

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端地址：http://localhost:5173

## Docker 部署

完整的 Docker 部署方案见 [docs/deployment.md](docs/deployment.md)。

```bash
# 构建并启动所有服务
cd docker
docker compose up -d --build

# 查看日志
docker compose logs -f backend
```

## API 接口

### 认证

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册（可选 company_name） |
| POST | `/api/auth/login` | 登录，返回 access + refresh token |
| POST | `/api/auth/refresh` | 刷新 access token |

### 问答与检索

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/query` | SSE 流式问答，支持 `date_from` / `date_to` 过滤 |
| GET | `/api/stats` | 数据与系统统计 |
| GET | `/api/health` | 健康检查 |

### 数据导入

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/ingest/trigger` | 触发数据采集（返回 task_id） |
| GET | `/api/ingest/status` | 全局导入状态 |
| GET | `/api/ingest/task/{task_id}` | 查询单个任务进度 |
| GET | `/api/ingest/tasks` | 列出当前用户所有活跃任务 |

### Deep Research

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/research` | 创建研究任务（异步执行） |
| GET | `/api/research/{task_id}` | 查询任务状态与结果 |
| GET | `/api/research/{task_id}/status` | 查询当前步骤进度 |
| GET | `/api/research/{task_id}/events` | SSE 实时进度流 |
| POST | `/api/research/{task_id}/cancel` | 取消运行中的任务 |

### 反馈

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/feedback` | 提交用户反馈（thumbs up/down + 原因） |
| GET | `/api/feedback/stats` | 反馈统计数据 |

更多细节见 http://localhost:8000/docs（Swagger UI）。

## 核心配置

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `ENV` | 运行环境 | `dev` |
| `DEBUG` | 调试模式 | `true` |
| `LLM_PROVIDER` | LLM 提供商 | `deepseek` |
| `LLM_MODEL` | LLM 模型名 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `VOLCENGINE_API_KEY` | 火山引擎 API Key | - |
| `MILVUS_HOST` | Milvus 主机 | `localhost` |
| `MILVUS_PORT` | Milvus 端口 | `19530` |
| `POSTGRES_HOST` | PostgreSQL 主机 | `localhost` |
| `POSTGRES_PORT` | PostgreSQL 端口 | `5432` |
| `JWT_SECRET` | JWT 签名密钥 | - |
| `LLM_CACHE` | LLM 响应缓存 | `true` |
| `PROMPT_VERSION` | Prompt 版本 | `v1` |

生产环境（`ENV=prod`）强制关闭 `llm_cache`、`retrieval_dump` 和 `debug`。

## 开发

### 后端

```bash
cd backend
make install          # 安装依赖
make dev              # 启动开发服务器
make lint             # 代码检查
uv run pytest         # 运行测试
```

### 前端

```bash
cd frontend
npm install           # 安装依赖
npm run dev           # 开发服务器
npm run build         # 生产构建
```

### 数据导入与评估

```bash
cd backend
# 导入金融数据
python scripts/seed_data.py --limit 10000
python scripts/import_rss_pipeline.py

# 检索质量评估
PYTHONPATH=src python scripts/evaluate_retrieval.py
# 目标: Precision@5 >= 0.8

# 端到端评估（检索 + 答案质量 + 引用覆盖率）
PYTHONPATH=src python scripts/evaluate_e2e.py --limit 5
# 目标: keyword_hit_rate >= 0.7, faithfulness >= 3.5, relevance >= 3.5
```

## Prompt 管理

Prompt 模板位于 `backend/src/agent/templates/`，按版本目录管理（`v1/`、`v2/`），通过 `current` 软链接指向当前版本。运行时通过 `PROMPT_VERSION` 环境变量选择。

LLM 响应缓存位于 `backend/data/llm_cache/{version}/`，缓存 key 包含模型、Prompt 版本和输入内容。

## 可观测性

- 每个请求生成 `trace_id`，通过 `X-Trace-ID` 响应头传播
- structlog 结构化日志，自动脱敏 API Key 等敏感信息
- 错误分级：可忽略错误（空检索）记录后继续，关键错误（Milvus 不可用、API Key 无效）中断请求
- 审计日志记录关键操作（查询、导入、研究任务）

## 许可证

[MIT License](LICENSE)
