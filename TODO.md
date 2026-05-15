# RAG News Intelligence — TODO

> 本文件已合并根目录 `TODO.md` 与原 `docs/todo.md`。现在只保留这一份根目录 TODO。
>
> 标记口径：`[x]` 表示代码或文档中已有可识别实现；`[ ]` 表示仍未完成、未接入主流程，或还缺少端到端验证。部分“有骨架但未闭环”的项会拆成已完成和待完成两条。

## 当前进度总览

- [x] News RAG 基础工程骨架已完成：FastAPI、React、Milvus、PostgreSQL、认证、采集器、LangGraph、LLM 客户端。
- [x] News RAG 问答主链路已有实现：查询 API、SSE 流式返回、来源面板、Milvus 检索、LLM 生成。
- [ ] News RAG 端到端稳定性仍需验证：本地服务、真实 API key、真实 Milvus 数据、前后端完整查询流程。
- [ ] Deep Research 仍未真正产品化：已有设计、schema、部分工具函数和 API 入口，但 Writer 仍是 stub，API 只跑 planner + retriever。
- [ ] 自动测试未通过：`uv run pytest` 当前因 `ModuleNotFoundError: No module named 'scripts'` 在收集阶段失败。

---

## 优先级说明

| 等级 | 定义 | 说明 |
|------|------|------|
| P0 | 阻塞 | 不完成就无法开始下一项 |
| P1 | 必须 | 本阶段必须完成 |
| P2 | 应该 | 重要但不紧急 |
| P3 | 可以 | 锦上添花或未来探索 |

---

## P0 — 基础设施与架构

- [x] 技术栈选型（Python + FastAPI + LangGraph + Embedding API + Milvus + React + Tailwind）
- [x] 完整版设计文档（`docs/full-design.md`）
- [x] MVP 设计文档（`docs/mvp-design.md`）
- [x] Deep Research Agent 接入设计（`docs/deep-research-agent-design.md`）
- [x] PostgreSQL schema 设计（companies / users / research_tasks / user_preferences / refresh_tokens / audit_logs）
- [x] PostgreSQL async 连接池配置（SQLAlchemy + asyncpg）
- [x] JWT 认证基础设施（密码哈希、access_token、refresh_token）
- [x] `ai_industry_articles` Milvus Collection schema + 索引 + user_id 字段
- [x] Supervisor + Multi-Tool 架构骨架（ResearchState + planner/retriever/analyst/checker/writer + research graph）
- [ ] Research Supervisor 主流程接入 Deep Research API

---

## 阶段 1 — 项目骨架

### 后端

- [x] 创建 `backend/src/` 目录结构
- [x] 创建 `backend/pyproject.toml` 并配置依赖
- [x] 配置 `pydantic-settings`
- [x] 配置 `.env` 示例与生产模板
- [x] 基础日志输出
- [x] trace_id 中间件

### Docker / 基础服务

- [x] 创建 `docker/docker-compose.yml`
- [x] Docker Compose 包含 Milvus、etcd、MinIO、PostgreSQL
- [ ] 验证本机容器全部启动并健康

### 前端

- [x] 创建 `frontend/` 项目（Vite + React + TypeScript）
- [x] 配置 Tailwind CSS
- [x] 创建基础组件、API、context、types 目录
- [ ] 补齐或清理未使用的前端组件入口

---

## 阶段 2 — Embedding + Milvus 存储

### Embedding

- [x] 实现 `vectorstore/embedding.py`（Embedding API 调用 + 分批 + 重试）
- [x] 实现同步与异步 embedding wrapper
- [x] 实现本地 embedding cache 类
- [ ] 使用真实 API key 验证返回 1024 维向量

### News Collection

- [x] 定义 `news_articles` Collection schema
- [x] 配置向量索引（IVF_FLAT + COSINE）
- [x] 实现向量搜索
- [x] 实现批量插入
- [x] 写入时生成 `content_hash`
- [ ] 实现真正的 content_hash 去重 / upsert
- [ ] 实现增量更新

### Chunk Collection / RSS 入库

- [x] 定义 `news_chunks` Collection schema
- [x] 实现 chunk 切分与 chunk store
- [x] 实现 RSS 全文采集 → MinIO → Chunk → Embedding → Milvus 导入脚本
- [ ] 将 `news_chunks` 接入主查询 API 或统一检索入口

### 数据导入

- [x] HuggingFace AG News seed 脚本
- [x] DatasetCollector 采集器
- [ ] 验证 Milvus 中已成功写入 1 万条记录
- [ ] 建立可重复的数据初始化命令和验收脚本

---

## 阶段 3 — 多路召回

- [x] 语义召回（向量 COSINE 搜索）
- [x] 关键词召回（Milvus expr `like` 查询）
- [x] 标题精确匹配（Milvus expr `like` 查询）
- [x] RRF 融合算法
- [x] 配置召回权重（语义 0.5 / 关键词 0.3 / 标题 0.2）
- [x] 多 query 结果按标题去重
- [x] 来源、语言、分类过滤逻辑
- [ ] 时间范围过滤
- [ ] 替换伪全文检索为 Milvus 正式全文检索或外部 BM25
- [ ] 三路召回真实数据验证
- [ ] Precision@5 / Recall / NDCG 达标验证

---

## 阶段 4 — News RAG LangGraph Agent

### LLM 与 Prompt

- [x] 实现 DeepSeek LLM client
- [x] 实现 OpenAI LLM client
- [x] 实现 Qwen LLM client
- [x] 支持 `.env` 切换 provider/model
- [x] 实现流式输出
- [x] 实现 LLM 文件缓存
- [x] Prompt 模板目录与 v1 模板
- [ ] Prompt 版本化 v2

### Agent 工作流

- [x] 定义 AgentState
- [x] 实现 query analysis 节点
- [x] 实现 retrieval planning 节点
- [x] 实现 retrieve 节点
- [x] 实现 evaluate relevance 节点
- [x] 实现 re_search 节点
- [x] 实现 answer generation 节点
- [x] 实现 self reflection 节点
- [x] 编译 LangGraph
- [x] 支持历史上下文参数
- [ ] 流式路径接入完整 LangGraph 质量闭环（当前跳过 evaluate/re_search/self_reflect）
- [ ] CLI 或 API 端到端验证：问题 → 检索 → 带来源答案
- [ ] 验证 LLM 缓存命中行为

---

## 阶段 5 — FastAPI

- [x] 创建 `api/app.py`
- [x] 配置 CORS
- [x] 配置 trace_id 响应头
- [x] 配置结构化日志
- [x] 实现 `POST /api/query`（SSE 流式）
- [x] 实现 `GET /api/stats`
- [x] 实现 `GET /api/health`
- [x] 实现 `POST /api/ingest/trigger`
- [x] 实现 `GET /api/ingest/status`
- [x] 注册 auth router
- [x] 注册 research router
- [ ] `/api/ingest/trigger` 从“采集计数”升级为“采集 + embedding + 入库”的完整异步任务
- [ ] 用 curl 或集成测试验证 `/api/query` SSE 输出
- [ ] 用 curl 或集成测试验证 `X-Trace-ID`

---

## 阶段 6 — React 前端

### 已实现

- [x] 7:3 分栏主布局
- [x] Clean Light 主题
- [x] 登录 / 注册页面
- [x] AuthContext 与 token 本地存储
- [x] ChatWindow
- [x] 消息气泡
- [x] SSE 流式文本显示
- [x] Markdown 渲染
- [x] 输入框、发送按钮、加载状态
- [x] SourcePanel
- [x] SourceCard
- [x] HealthBadge
- [x] IngestPanel
- [x] Dashboard 组件
- [x] HistoryPanel 组件

### 待补齐

- [ ] FilterBar 接入主查询流程
- [ ] CompareView 接入主界面
- [ ] Deep Research 入口页面
- [ ] 研究进度展示（Planner → Retriever → Analyst → Checker → Writer）
- [ ] Markdown 报告预览
- [ ] PPT 大纲 JSON 预览
- [ ] 前端完整查询流程验收
- [ ] 响应式布局验收

---

## 阶段 7 — 认证、用户与任务

- [x] 注册接口：`POST /api/auth/register`
- [x] 登录接口：`POST /api/auth/login`
- [x] Token 刷新接口：`POST /api/auth/refresh`
- [x] Bearer token 解析依赖：`get_current_user`
- [x] 自动创建公司
- [x] Refresh token hash 存储
- [x] ResearchTask ORM
- [x] Deep Research 任务写入 `research_tasks`
- [ ] refresh token 与 token_id 严格绑定校验
- [ ] 请求级认证中间件统一注入 user_id/company_id
- [ ] 公司配额检查
- [ ] 任务完成后 increment quota
- [ ] 审计日志写入
- [ ] 用户偏好设置页
- [ ] Planner 读取并注入用户偏好

---

## 阶段 8 — Deep Research / Multi-Tool

### 子 Tool

- [x] `planner` Tool：意图分析、受众识别、研究计划、子问题拆解
- [x] `retriever` Tool：根据子问题检索证据并去重
- [x] `analyst` Tool：LLM 分析趋势、机会、风险，带 fallback
- [x] `checker` Tool：LLM 核查覆盖、可信度、冲突、缺口，带 fallback
- [ ] `writer` Tool：当前仍是 stub，需要生成真实 Markdown 报告、PPT 大纲和逐页内容
- [ ] 子 Tool 输出格式统一并做 schema 校验
- [ ] Tool 调用重试机制
- [ ] JSON 解析失败统一降级
- [ ] 单步重试 API：`POST /api/research/{task_id}/retry?step=xxx`
- [ ] 失败步骤和 retry_count 写入任务表

### Orchestrator / API

- [x] ResearchState 定义
- [x] Research graph 骨架
- [x] `POST /api/research` API 入口
- [x] `GET /api/research/{task_id}` 查询任务结果
- [ ] `POST /api/research` 接入完整 research graph（当前只同步执行 planner + retriever）
- [ ] Checker 发现缺口时补检索闭环
- [ ] Writer 输出写入 result_markdown / result_slides
- [ ] gaps_identified / conflicts_detected 写入任务表
- [ ] Deep Research SSE 或任务进度流

### 报告质量评估

- [ ] 自动指标：证据覆盖率、来源多样性、时效性、可信度、缺口识别率
- [ ] 质量分数写入 `research_tasks`
- [ ] LLM 评审报告质量
- [ ] 用户反馈评分

---

## 阶段 9 — 数据采集扩展

- [x] RSS 采集器
- [x] Hacker News API 采集器
- [x] HuggingFace Dataset 采集器
- [x] RSS 全文抓取与导入脚本
- [x] MinIO 原文存储
- [ ] AI 行业 RSS 采集 pipeline 接入 `ai_industry_articles`
- [ ] 定时采集调度
- [ ] Reddit API 采集器
- [ ] Scrapy 爬虫
- [ ] 数据来源可信度评分

---

## 阶段 10 — 调试、评估与可观测性

- [x] LangSmith tracing 配置函数
- [x] 敏感信息脱敏日志
- [x] 基础错误类型
- [x] `scripts/evaluate_retrieval.py`
- [x] 默认测试查询集
- [x] Precision / Recall / NDCG 计算
- [ ] 修复 pytest 收集失败
- [ ] 增加 API 集成测试
- [ ] 增加 Agent 图测试
- [ ] 增加 Deep Research 工具测试
- [ ] 验证 `.env.prod` 中 DEBUG=false
- [ ] 验证生产环境关闭 LLM 缓存
- [ ] 验证生产环境禁止全量 dump

---

## 阶段 11 — 部署与运维

- [x] Docker Compose 本地基础服务
- [ ] 后端 Dockerfile
- [ ] 前端生产构建配置
- [ ] Nginx 反向代理
- [ ] 域名与 HTTPS
- [ ] CI/CD
- [ ] 部署文档
- [ ] Redis LLM 响应缓存
- [ ] Redis 公司级限流
- [ ] Redis 分布式锁

---

## 设计决策记录

### Multi-Agent → Supervisor + Multi-Tool

- [x] 决策：当前阶段采用 1 个 Supervisor + 多个 Tool Function，而不是多个独立 Agent 自由对话。
- [x] 原因：流程相对固定，中央调度更可控，更方便调试、缓存和评估。
- [ ] 后续：等 Deep Research 主链路稳定后，再评估是否拆分领域型子 Agent。

### JWT vs API Key

- [x] 决策：采用 JWT（access_token + refresh_token），而不是简单 API Key。
- [x] 原因：ToB 场景需要多用户、团队、配额、权限和 token 过期机制。
- [ ] 后续：补齐 refresh token 严格校验、配额和审计日志。

### PPT 交付

- [x] 决策：第一阶段后端生成结构化 JSON，前端渲染预览。
- [ ] 后续：生成可下载 PPTX 或接入导出服务。

---

## 里程碑

| 里程碑 | 状态 | 验收标准 |
|--------|------|---------|
| M1: News RAG 骨架 | 已完成 | 后端、前端、Milvus、LLM、基础 Agent 代码就绪 |
| M2: News RAG 可演示 | 待验证 | 前后端完整查询流程跑通，答案带来源 |
| M3: Deep Research 骨架 | 已完成 | schema、认证、research graph、tool 函数和 API 入口就绪 |
| M4: Deep Research MVP | 未完成 | planner → retriever → analyst → checker → writer 完整报告闭环 |
| M5: ToB MVP | 未完成 | 登录、配额、任务历史、报告预览、质量评估、部署文档 |

- [ ] 编写部署文档
- [ ] 配置 CI/CD
- [ ] 配置 Nginx 反向代理
- [ ] 配置域名和 HTTPS

---

## 里程碑

| 里程碑 | 目标 | 验收标准 |
|--------|------|---------|
| M1 | 基础设施就绪 | Docker 启动 + Milvus 连接成功 |
| M2 | 数据层完成 | 1万条数据导入 + 可检索 |
| M3 | RAG 跑通 | CLI 查询返回带来源答案 |
| M4 | API 就绪 | `/api/query` SSE 流正常 |
| M5 | 前端完成 | 完整 UI 交互跑通 |
| M6 | MVP 交付 | M1-M5 全部完成 |
| M7 | 完整版 | 阶段8所有模块完成 |
