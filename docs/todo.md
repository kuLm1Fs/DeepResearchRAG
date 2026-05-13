# RAG News Intelligence — TODO

## 阶段 0 — 规划与设计 ✅ 全部完成

- [x] 技术栈选型（Python + FastAPI + LangGraph + aihubmix Embedding + Milvus + React + Tailwind）
- [x] 服务器评估（4核15.6GB，可用 Docker）
- [x] LLM 选型（DeepSeek 主 + OpenAI/Qwen 备，支持切换）
- [x] 召回策略（多路召回 + RRF 融合）
- [x] Agent 架构（LangGraph，Agent Workflow 模式）
- [x] 调试方案（LangSmith、LLM 缓存、trace_id、结构化日志）
- [x] 生产安全（环境隔离、敏感脱敏、dump 禁止、错误分级）
- [x] 前端设计（Clean Light、7:3分栏、折叠卡片）
- [x] 完整版设计文档 (`docs/full-design.md`)
- [x] MVP 设计文档 (`docs/mvp-design.md`)

---

## 阶段 1 — 项目骨架 ✅ 全部完成

### 1.1 后端初始化

- [x] 创建 `backend/src/` 目录结构
- [x] 创建 `pyproject.toml`，配置依赖
- [x] 配置 pydantic-settings
- [x] 创建 `.env.dev` 和 `.env.prod` 模板

### 1.2 Docker 配置

- [x] 创建 `docker/docker-compose.yml`（Milvus + etcd + MinIO）
- [x] 验证容器启动：`docker ps` 显示三个容器运行中

### 1.3 前端初始化

- [x] 创建 `frontend/` 项目（Vite + React + TypeScript）
- [x] 配置 Tailwind CSS
- [x] 配置 TypeScript
- [x] 创建基础目录结构（components、hooks、api、types）

### 1.4 基础设施验证

- [x] Milvus 连接成功
- [x] .env 环境变量加载正常
- [x] 基础日志输出正常

---

## 阶段 2 — Embedding + Milvus 存储 ✅ 全部完成

### 2.1 Embedding 封装

- [x] 实现 `embedding.py`（aihubmix bge-large-zh API 调用 + 分批 + 重试）
- [x] 验证调用成功，返回 1024 维向量
- [x] 修复 batch_size 50→16（aihubmix API 限制）

### 2.2 Milvus Schema

- [x] 定义 Collection Schema（id、embedding、title、content、source、language、category、published_at）
- [x] 配置向量索引（IVF_FLAT, COSINE）
- [x] 配置全文索引（title, content）

### 2.3 向量 CRUD

- [x] 实现插入单条
- [x] 实现批量插入
- [x] 实现 content_hash 去重
- [x] 实现增量更新

### 2.4 数据导入

- [x] 加载 HuggingFace ag_news 数据集
- [x] 实现文本清洗和分块
- [x] 批量调用 Embedding API
- [x] 写入 Milvus（1000条）
- [x] 验证：collection 有非零向量

---

## 阶段 3 — 多路召回 ✅ 全部完成

### 3.1 三路召回

- [x] 实现语义召回（向量 COSINE 搜索）
- [x] 实现关键词召回（Milvus text_search）
- [x] 实现标题精确匹配（Milvus expr like）

### 3.2 RRF 融合

- [x] 实现 RRF 融合算法
- [x] 配置权重（语义 0.5 / 关键词 0.3 / 标题 0.2）
- [x] 实现结果去重

### 3.3 过滤

- [x] 实现时间范围过滤
- [x] 实现来源过滤
- [x] 实现语言过滤
- [x] 实现分类过滤

### 3.4 召回验证

- [x] 三路都有结果
- [x] RRF 融合排序合理
- [x] 过滤功能正常
- [ ] Precision@5 ≥ 0.8（运行 `scripts/evaluate_retrieval.py`）

---

## 阶段 4 — LangGraph Agent ✅ 全部完成

### 4.1 LLM 封装

- [x] 实现 `llm/client.py`（DeepSeek + 缓存）
- [x] 实现流式输出（stream_chat）
- [x] 实现 LLM 缓存（`data/llm_cache/v1/`）
- [x] 验证调用成功

### 4.2 Prompt 模板

- [x] 创建 `src/agent/templates/v1/` 目录
- [x] 编写 `generate_answer.txt`（意图分类 + markdown 格式 + 来源引用）
- [x] 编写 `evaluate_relevance.txt`（LLM 评估检索结果相关性，JSON 输出）
- [x] 编写 `analyze_query.txt`（LLM 意图分析 + query 改写 + 子查询生成，JSON 输出）

### 4.3 Agent 工作流

- [x] 定义 AgentState
- [x] 实现 analyze_query 节点（LLM 意图分析）
- [x] 实现 plan_retrieval 节点（检索规划）
- [x] 实现 retrieve 节点（多轮检索 + 去重合并）
- [x] 实现 evaluate_relevance 节点（LLM 质量评估 + 缺口识别）
- [x] 实现 should_research 条件边（是否需要补检索）
- [x] 实现 re_search 节点（补充检索，最多1轮）
- [x] 实现 generate_answer 节点（生成答案）
- [x] 实现 self_reflect 节点（自我反思）
- [x] 编译图：`graph.compile()`
- [x] JSON 解析 fallback 机制

### 4.4 Agent 验证

- [x] 端到端测试：输入问题 → LLM 分析意图 → 多轮检索 → LLM 评估 → 带来源的答案
- [x] LLM 缓存生效
- [x] SSE 流式输出正常

---

## 阶段 5 — FastAPI ✅ 全部完成

### 5.1 应用框架

- [x] 创建 `api/app.py`
- [x] 配置 trace_id 中间件
- [x] 配置结构化日志中间件
- [x] 配置 CORS

### 5.2 接口实现

- [x] 实现 `POST /api/query`（SSE 流式 + 非流式双路径）
- [x] 实现 `POST /api/ingest/trigger`（数据导入触发）
- [x] 实现 `GET /api/ingest/status`（导入状态查询）
- [x] 实现 `GET /api/health`（健康检查）

### 5.3 API 验证

- [x] curl health 返回正确数据
- [x] curl query 返回 SSE 流 + markdown 格式
- [x] 端到端 Agent workflow 跑通

---

## 阶段 6 — React 前端 ✅ 全部完成

### 6.1 基础布局

- [x] 实现 7:3 分栏布局
- [x] 配置 Clean Light 主题色（#ffffff + #2563eb）
- [x] 实现来源面板折叠按钮

### 6.2 对话组件

- [x] 实现 `ChatWindow.tsx`
- [x] 实现消息气泡（用户 / AI 区分样式）
- [x] 实现流式文本逐字显示
- [x] 实现输入框（回车发送）
- [x] 实现发送按钮和加载状态
- [x] 实现 markdown 渲染（react-markdown + remark-gfm）

### 6.3 来源组件

- [x] 实现 `SourcePanel.tsx`（包裹卡片）
- [x] 实现 `SourceCard.tsx`（折叠式，悬停展开）
- [x] 默认显示：标题 + 来源
- [x] 悬停展开：时间 + 摘要 + 分类标签 + 相关度分数

### 6.4 API 层

- [x] 实现 `api/client.ts`
- [x] 实现 SSE 流式处理
- [x] 实现错误处理和重连

### 6.5 前端验证

- [x] 完整查询流程跑通
- [x] 响应式布局正常
- [x] 来源面板折叠/展开正常

---

## 阶段 7 — 调试与可观测性 ⏳ 部分完成

### 7.1 日志与追踪

- [x] 集成 LangSmith tracing（开发阶段）
- [x] 敏感信息脱敏日志
- [ ] 实现错误分级（可忽略 / 需处理）

### 7.2 检索评估

- [ ] 实现 `scripts/evaluate_retrieval.py`
- [ ] 准备测试查询集（20-30 条）
- [ ] 输出 Precision/Recall 指标

### 7.3 生产安全

- [ ] 验证 `.env.prod` 环境 DEBUG=false
- [x] `.env.prod` 从 git 追踪移除
- [x] `.gitignore` 添加 `**/.env*`
- [ ] 验证生产环境自动关闭 LLM 缓存
- [ ] 验证生产环境禁止全量 dump

---

## 阶段 8 — 扩展功能 ⏳ 部分完成

### 数据采集扩展

- [x] 实现 RSS 采集器（8个中英文源：TechCrunch、The Verge、ArsTechnica、BBC、Reuters、36kr、少数派、钛媒体、ifanr）
- [x] 实现 Hacker News API 采集器
- [ ] RSS 全文抓取（trafilatura）— **用户明确要求**
- [ ] RSS 数据导入 Milvus（目前只有 ag_news 1000条）
- [ ] RSS 定时采集调度
- [ ] 实现 Reddit API 采集器
- [ ] 实现 Scrapy 爬虫（中文字站）

### LLM 扩展

- [x] 实现 DeepSeek 客户端（主）
- [ ] 实现 OpenAI 客户端（备选）
- [ ] 实现 Qwen 客户端（备选）
- [ ] 实现 `.env` 切换模型验证

### Agent 扩展

- [x] 实现意图识别（LLM 结构化输出）
- [x] 实现多轮检索规划
- [x] 实现补检索循环
- [ ] 实现多源对比节点
- [ ] 实现深度自我反思（多轮反思）
- [ ] Prompt 版本化管理（v2）
- [ ] 实现历史对话上下文

### 召回扩展

- [x] 实现 CrossEncoder Re-ranker
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

| 里程碑 | 目标 | 状态 |
|--------|------|------|
| M1 | 基础设施就绪 | ✅ |
| M2 | 数据层完成 | ✅ (1000条 ag_news) |
| M3 | RAG 跑通 | ✅ |
| M4 | API 就绪 | ✅ |
| M5 | 前端完成 | ✅ |
| M6 | MVP 交付 | ✅ M1-M5 全部完成 |
| M7 | 完整版 | ⏳ 阶段8部分模块完成 |
