# RAG News Intelligence — TODO

## 阶段 0 — 规划与设计 ✅

- [x] 技术栈选型（Python + FastAPI + LangGraph + 火山引擎 Embedding + Milvus 全量版 + React + Tailwind）
- [x] 服务器评估（4核15.6GB，可用 Docker）
- [x] LLM 选型（DeepSeek 主 + OpenAI/Qwen 备，支持切换）
- [x] 召回策略（多路召回 + RRF 融合）
- [x] Agent 架构（LangGraph，Pipeline 模式）
- [x] 调试方案（LangSmith、LLM 缓存、trace_id、结构化日志）
- [x] 生产安全（环境隔离、敏感脱敏、dump 禁止、错误分级）
- [x] 前端设计（Clean Light、7:3分栏、折叠卡片）
- [x] 完整版设计文档 (`docs/full-design.md`)
- [x] MVP 设计文档 (`docs/mvp-design.md`)

---

## 阶段 1 — 项目骨架

### 1.1 后端初始化

- [ ] 创建 `backend/src/` 目录结构
- [ ] 创建 `pyproject.toml`，配置依赖
- [ ] 配置 pydantic-settings
- [ ] 创建 `.env.dev` 和 `.env.prod` 模板

### 1.2 Docker 配置

- [ ] 创建 `docker/docker-compose.yml`（Milvus + etcd + MinIO）
- [ ] 验证容器启动：`docker ps` 显示三个容器运行中

### 1.3 前端初始化

- [ ] 创建 `frontend/` 项目（Vite + React + TypeScript）
- [ ] 配置 Tailwind CSS
- [ ] 配置 TypeScript
- [ ] 创建基础目录结构（components、hooks、api、types）

### 1.4 基础设施验证

- [ ] Milvus 连接成功
- [ ] .env 环境变量加载正常
- [ ] 基础日志输出正常

---

## 阶段 2 — 火山引擎 Embedding + Milvus 存储

### 2.1 Embedding 封装

- [ ] 实现 `volcengine_client.py`（API 调用 + 分批 + 重试）
- [ ] 验证调用成功，返回 1024 维向量

### 2.2 Milvus Schema

- [ ] 定义 Collection Schema（id、embedding、title、content、source、language、category、published_at）
- [ ] 配置向量索引（IVF_FLAT, COSINE）
- [ ] 配置全文索引（title, content）

### 2.3 向量 CRUD

- [ ] 实现插入单条
- [ ] 实现批量插入
- [ ] 实现 content_hash 去重
- [ ] 实现增量更新

### 2.4 数据导入

- [ ] 加载 HuggingFace ag_news 数据集
- [ ] 实现文本清洗和分块
- [ ] 批量调用 Embedding API
- [ ] 写入 Milvus（1万条）
- [ ] 验证：`collection.num_entities == 10000`

---

## 阶段 3 — 多路召回

### 3.1 三路召回

- [ ] 实现语义召回（向量 COSINE 搜索）
- [ ] 实现关键词召回（Milvus text_search）
- [ ] 实现标题精确匹配（Milvus expr like）

### 3.2 RRF 融合

- [ ] 实现 RRF 融合算法
- [ ] 配置权重（语义 0.5 / 关键词 0.3 / 标题 0.2）
- [ ] 实现结果去重

### 3.3 过滤

- [ ] 实现时间范围过滤
- [ ] 实现来源过滤
- [ ] 实现语言过滤
- [ ] 实现分类过滤

### 3.4 召回验证

- [ ] 三路都有结果
- [ ] RRF 融合排序合理
- [ ] 过滤功能正常
- [ ] Precision@5 ≥ 0.8（运行 `scripts/evaluate_retrieval.py`）

---

## 阶段 4 — LangGraph Agent

### 4.1 LLM 封装

- [ ] 实现 `llm/client.py`（DeepSeek + 缓存）
- [ ] 实现流式输出
- [ ] 实现 LLM 缓存（`data/llm_cache/v1/`）
- [ ] 验证调用成功

### 4.2 Prompt 模板

- [ ] 创建 `src/agent/templates/` 目录
- [ ] 编写 `generate_answer.txt`（基于检索结果生成答案 + 引用）
- [ ] 编写 `evaluate_relevance.txt`（评估检索结果相关性）

### 4.3 Agent 工作流

- [x] 定义 AgentState
- [x] 实现 retrieve 节点（多路召回）
- [x] 实现 evaluate 节点（评估相关性）
- [x] 实现 generate 节点（生成答案）
- [x] 实现 reflect 节点（自我反思）
- [x] 实现条件边（结果不够则重新检索）
- [x] 编译图：`graph.compile()`

### 4.4 Agent 验证

- [ ] CLI 测试：输入问题 → 带来源的答案
- [ ] LLM 缓存生效（第二次相同查询不调 API）

---

## 阶段 5 — FastAPI

### 5.1 应用框架

- [ ] 创建 `api/app.py`
- [ ] 配置 trace_id 中间件
- [ ] 配置结构化日志中间件
- [ ] 配置 CORS

### 5.2 接口实现

- [ ] 实现 `POST /api/query`（SSE 流式）
- [ ] 实现 `GET /api/stats`（返回数量统计）
- [ ] 实现 `GET /api/health`

### 5.3 API 验证

- [ ] `curl localhost:8000/api/stats` 返回正确数据
- [ ] `curl -X POST /api/query -d '{"query":"AI news"}'` 返回 SSE 流
- [ ] 响应头包含 `X-Trace-ID`

---

## 阶段 6 — React 前端

### 6.1 基础布局

- [ ] 实现 7:3 分栏布局
- [ ] 配置 Clean Light 主题色（#ffffff + #2563eb）
- [ ] 实现来源面板折叠按钮

### 6.2 对话组件

- [ ] 实现 `ChatWindow.tsx`
- [ ] 实现消息气泡（用户 / AI 区分样式）
- [ ] 实现流式文本逐字显示
- [ ] 实现输入框（回车发送）
- [ ] 实现发送按钮和加载状态

### 6.3 来源组件

- [ ] 实现 `SourcePanel.tsx`（包裹卡片）
- [ ] 实现 `SourceCard.tsx`（折叠式，悬停展开）
- [ ] 默认显示：标题 + 来源
- [ ] 悬停展开：时间 + 摘要 + 分类标签 + 相关度分数

### 6.4 API 层

- [ ] 实现 `api/client.ts`
- [ ] 实现 SSE 流式处理
- [ ] 实现错误处理和重连

### 6.5 前端验证

- [ ] 完整查询流程跑通（输入 → 发送 → 流式显示答案 → 显示来源卡片）
- [ ] 响应式布局正常
- [ ] 来源面板折叠/展开正常

---

## 阶段 7 — 调试与可观测性

### 7.1 日志与追踪

- [ ] 集成 LangSmith tracing（开发阶段）
- [ ] 敏感信息脱敏日志
- [ ] 实现错误分级（可忽略 / 需处理）

### 7.2 检索评估

- [ ] 实现 `scripts/evaluate_retrieval.py`
- [ ] 准备测试查询集（20-30 条）
- [ ] 输出 Precision/Recall 指标

### 7.3 生产安全

- [ ] 验证 `.env.prod` 环境 DEBUG=false
- [ ] 验证生产环境自动关闭 LLM 缓存
- [ ] 验证生产环境禁止全量 dump

---

## 阶段 8 — 扩展功能（完整版）

### 数据采集扩展

- [ ] 实现 RSS 采集器（中英文源）
- [ ] 实现 Hacker News API 采集器
- [ ] 实现 Reddit API 采集器
- [ ] 实现 Scrapy 爬虫（中文字站）
- [ ] 实现定时采集调度

### LLM 扩展

- [ ] 实现 OpenAI 客户端（备选）
- [ ] 实现 Qwen 客户端（备选）
- [ ] 实现 `.env` 切换模型

### Agent 扩展

- [ ] 实现意图识别（LLM 结构化输出）
- [ ] 实现规则路由 + LLM 兜底
- [ ] 实现多源对比节点
- [ ] 实现深度自我反思
- [ ] Prompt 版本化管理
- [ ] 实现历史对话上下文

### 召回扩展

- [ ] 实现 Re-ranker 精排
- [ ] 实现时间衰减加权
- [ ] 实现来源质量加权

### 前端扩展

- [ ] 实现过滤栏（语言、时间、来源、分类）
- [ ] 实现多源对比视图
- [ ] 实现数据概览仪表盘
- [ ] 实现历史查询记录

### 部署

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