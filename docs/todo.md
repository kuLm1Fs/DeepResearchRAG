# RAG News Intelligence — TODO

## 优先级说明

| 等级 | 定义 | 说明 |
|------|------|------|
| P0 | 阻塞 | 不完成就无法开始下一项 |
| P1 | 必须 | 本阶段必须完成 |
| P2 | 应该 | 重要但不紧急 |
| P3 | 可以 | 锦上添花 or 未来探索 |

---

## P0 — 阻塞项

> 不完成 P0，后续所有工作无法开始。

- [x] **P0-1** 新建 `ai_industry_articles` Milvus Collection（Schema + 索引 + user_id 字段）
- [x] **P0-2** Supervisor + Multi-Tool 架构（ResearchState + 5个Tool函数 + Supervisor prompt + LLM路由）
- [x] **P0-3** PostgreSQL 数据库初始化（执行 schema.sql + 连接池配置 + SQLAlchemy/asyncpg）
- [x] **P0-4** JWT 认证基础设施（bcrypt密码哈希 + JWT签名密钥 + access_token/refresh_token 生成）✅ `c71b688` → `a4520ea`（补测+修复）

---

## P1 — 本阶段必须完成

> 核心链路必须跑通的功能。

### 子 Tool 实现

- [ ] **P1-1** `planner` Tool（意图分析 + 受众识别 + 研究计划 + 子问题拆解 → JSON输出）
- [ ] **P1-2** `retriever` Tool（调用 MultiPathRetriever + 多轮检索 + 结果合并去重 → Evidence列表）
- [ ] **P1-3** `analyst` Tool（趋势分析 + 机会分析 + 风险分析 → 结构化JSON输出）
- [ ] **P1-4** `checker` Tool（来源可信度 / 时效 / 缺口检测 + 冲突检测低优先级 → 检查报告）
- [ ] **P1-5** `writer` Tool（Markdown报告 + PPT大纲JSON + 逐页内容JSON → 三种输出）

### 数据层

- [ ] **P1-6** AI 行业 RSS 采集 pipeline（36氪、虎嗅、TechCrunch、Ars Technica）
- [ ] **P1-7** 火山引擎 Embedding 接入 `ai_industry_articles` collection
- [ ] **P1-8** 子 Tool 输出格式统一（统一 JSON 结构 + task_id + 缺口标记）

### Supervisor 集成

- [ ] **P1-9** Research Orchestrator（LLM路由 + 工具调用 + 条件分支：缺口大时返回retriever补检）
- [ ] **P1-10** 任务记忆写入（research_tasks 表 + result_markdown/slides_json 存储）

### 记忆管理层

- [ ] **P1-10a** Working Memory（LangGraph State 定义 + 中间状态流转）
- [ ] **P1-10b** 记忆分层实现（Working → Evidence → Task → User 四层架构）
- [ ] **P1-10c** 用户偏好收集（显式：设置页面 + 隐式：从行为推断）
- [ ] **P1-10d** 偏好读取与注入（研究开始时 Planner 自动读取 user_preferences）

### 容错处理

- [ ] **P1-10e** Tool 调用重试机制（指数退避，最多3次）
- [ ] **P1-10f** JSON 解析失败降级（返回 fallback 结果，不阻塞流程）
- [ ] **P1-10g** 死循环防护（MAX_TOOL_CALLS 限制）
- [ ] **P1-10h** 分步重试（支持单步重试：POST /api/research/{task_id}/retry?step=xxx）
- [ ] **P1-10i** 失败记录（research_tasks.failed_step + retry_count）

### API

- [ ] **P1-11** Deep Research API 入口（`POST /api/research` + 配额检查）

### 认证与用户

- [ ] **P1-12** 注册接口（`POST /api/auth/register`）+ 自动创建公司
- [ ] **P1-13** 登录接口（`POST /api/auth/login`）+ JWT token 返回
- [ ] **P1-14** Token 刷新（`POST /api/auth/refresh`）+ refresh_token 机制
- [ ] **P1-15** 认证中间件（JWT验证 + user_id/company_id 注入 + 数据隔离）
- [ ] **P1-16** 配额控制（公司quota_limit检查 + 任务完成时increment + 超出拒绝）

### 报告质量评估

- [ ] **P1-17** 方案A：自动指标评估（证据覆盖率 / 来源多样性 / 时效性 / 可信度 / 缺口识别率）
- [ ] **P1-18** 质量分数写入 research_tasks（quality_score + metrics JSON）

### 前端

- [ ] **P1-17** 登录/注册页面
- [ ] **P1-18** Deep Research 入口页面（和 RAG 问答分开入口）
- [ ] **P1-19** 研究进度展示（Planner → Retriever → Analyst → Checker → Writer 每步状态 + 实时日志）
- [ ] **P1-20** Markdown 报告预览（支持渲染 + 来源链接可点击）
- [ ] **P1-21** PPT 大纲 JSON 预览（前端渲染展示）

---

## P2 — 重要但不紧急

> P1 完成后做，增强稳定性和可复用性。

- [ ] **P2-1** 用户偏好存储（user_preferences 表 + 设置页面）
- [ ] **P2-2** 任务历史列表（查看历史研究 + 重新运行）
- [ ] **P2-3** 报告导出（下载 .md 文件）
- [ ] **P2-4** 子 Tool 独立测试脚本（每个函数可单独运行验证）
- [ ] **P2-5** 检索质量评估（Precision@5 达标）
- [ ] **P2-6** Admin 成员管理（`POST /api/admin/users` + 禁用/启用用户）
- [ ] **P2-7** 公司配额管理（admin 查看/修改公司配额）
- [ ] **P2-8** Redis LLM 响应缓存（替代文件缓存，跨进程共享 + TTL 自动过期）
- [ ] **P2-9** 方案B：LLM 评审（另一个 LLM 评审报告质量，输出多维度打分）
- [ ] **P2-10** 方案C：用户反馈（研究完成后弹窗打分，存入 audit_logs）

---

## P3 — 锦上添花 / 未来探索

> 后期增强，不影响核心价值交付。

### 功能增强

- [ ] **P3-1** 预设分析环节（Planner 增加"已知边界 + 可信度排序"），见 `docs/issues.md`
- [ ] **P3-2** 多源对比节点（Analyst 内部增加来源对比逻辑）
- [ ] **P3-3** LLM 缓存升级为版本化（`data/llm_cache/v2/`）
- [ ] **P3-4** Prompt 版本化管理（`src/agent/templates/v2/`）
- [ ] **P3-5** 冲突检测升级为正式实现（Writer 标注冲突内容）

### 数据增强

- [ ] **P3-6** 中文 RSS 源扩展（InfoQ、少数派、IT之家）
- [ ] **P3-7** Hacker News API 采集接入 `ai_industry_articles`
- [ ] **P3-8** HuggingFace 数据集导入（AG News / Multi-News）
- [ ] **P3-9** 数据来源可信度评分（`credibility_score` 字段维护）

### 缓存与限流

- [ ] **P3-10** Redis 热点研究结果缓存（相似问题加速返回）
- [ ] **P3-11** Redis 公司级限流（配额控制，替代 PostgreSQL）
- [ ] **P3-12** Redis 分布式锁（多实例部署时采集任务协调）

### 前端增强

- [ ] **P3-6** PPT 大纲预览页面（前端 JSON 渲染）
- [ ] **P3-7** 多源对比视图（同一事件不同来源报道对比）
- [ ] **P3-8** 数据概览仪表盘（来源分布、分类分布、时间趋势）
- [ ] **P3-9** 用户偏好设置页面
- [ ] **P3-10** Admin 后台（公司管理、成员管理、配额管理）

### 缓存与限流

- [ ] **P3-11** Redis 热点研究结果缓存（相似问题加速返回）
- [ ] **P3-12** Redis 公司级限流（配额控制，替代 PostgreSQL）
- [ ] **P3-13** Redis 分布式锁（多实例部署时采集任务协调）

### 可观测性

- [ ] **P3-14** LangSmith tracing 接入 Deep Research Agent
- [ ] **P3-15** 任务执行耗时监控（每个子 Tool 耗时）
- [ ] **P3-16** 方案D：对比基准评估（准备标准答案数据集，定期跑自动化对比）

### 部署

- [ ] **P3-17** PostgreSQL Docker 部署
- [ ] **P3-18** Nginx 反向代理配置
- [ ] **P3-19** 部署文档

---

## 里程碑

| 里程碑 | 包含项 | 验收标准 |
|--------|--------|---------|
| M1: 基础设施就绪 | P0 | Collection + DB + 认证骨架完成 |
| M2: 核心链路跑通 | P1 子Tool部分 | 5个Tool全通 + 报告生成 |
| M3: 前端集成 | P1 前端部分 | 登录 + 研究进度 + 报告预览 |
| M4: MVP 交付 | M1 + M2 + M3 | 完整端到端可用（ToB多用户） |
| M5: 增强 | P2 + P3 | 历史记录、PPT、Admin后台 |

---

## 阶段 0 — 规划与设计 ✅

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

### Deep Research 新增设计 ✅

- [x] Agent架构：多图+Supervisor → **修正为 Supervisor + Multi-Tool**（见下方设计决策）
- [x] 子Agent职责边界（Planner 拆解+受众 / Analyst 趋势+机会+风险 / Checker 完整+冲突低优先级 / Writer Markdown+PPT大纲+逐页内容）
- [x] LLM路由设计（可跳过步骤，缺口大时返回retriever补检）
- [x] 数据库设计（companies + users + research_tasks + user_preferences + refresh_tokens + audit_logs），见 `docs/schema.sql` 和 `docs/schema.md`
- [x] 认证方案：API Key → **JWT**（ToB多用户场景）
- [x] PostgreSQL 表结构（6张表 + 索引 + 触发器），见 `docs/schema.sql`
- [x] ai_industry_articles Collection Schema（15个字段），见上方 P0-1
- [x] PPT交付：后端生成JSON，前端渲染

---

## 阶段 1 — 项目骨架 ✅

- [x] 后端目录结构 + pyproject.toml
- [x] Docker Compose (Milvus + etcd + MinIO)
- [x] 前端项目 (Vite + React + Tailwind)
- [x] 基础设施验证

---

## 阶段 2 — Embedding + Milvus 存储 ✅

- [x] embedding.py (aihubmix bge-large-zh API + 分批 + 重试)
- [x] Collection Schema + 向量索引
- [x] 向量 CRUD + content_hash 去重
- [x] HuggingFace ag_news 数据导入

---

## 阶段 3 — 多路召回 ✅

- [x] 语义召回 + 关键词召回 + 标题精确匹配
- [x] RRF 融合
- [x] 时间/来源/语言/分类过滤
- [x] Precision@5 ≥ 0.8

---

## 阶段 4 — LangGraph Agent ✅

- [x] LLM 封装（DeepSeek + 缓存 + 流式）
- [x] Prompt 模板 (v1)
- [x] Agent 工作流（8节点 + 条件边）
- [x] 端到端测试通过

---

## 阶段 5 — FastAPI ✅

- [x] trace_id 中间件 + 结构化日志
- [x] `/api/query` (SSE 流式)
- [x] `/api/ingest` 接口
- [x] `/api/health`

---

## 阶段 6 — React 前端 ✅

- [x] 7:3 分栏布局 + Clean Light 主题
- [x] ChatWindow (流式 + markdown)
- [x] SourcePanel + SourceCard (折叠式)
- [x] 过滤栏 + Dashboard + HistoryPanel

---

## 阶段 7 — 调试与可观测性 ⏳

- [x] LangSmith tracing
- [x] 敏感信息脱敏
- [x] 错误分级
- [x] evaluate_retrieval.py
- [x] 生产安全检查

---

## 阶段 8 — 扩展功能 ⏳

### 数据采集

- [x] RSS 采集器（8个中英文源）
- [x] Hacker News API 采集器
- [x] RSS 全文抓取 (trafilatura)
- [x] RSS 数据导入 Milvus
- [ ] RSS 定时采集调度
- [ ] Reddit API 采集器
- [ ] Scrapy 爬虫

### LLM

- [x] DeepSeek / OpenAI / Qwen 客户端
- [x] `.env` 切换模型

### Agent

- [x] 意图识别
- [x] 多轮检索规划
- [x] 补检索循环
- [x] 多源对比
- [x] 自我反思
- [x] 历史对话上下文
- [ ] Prompt 版本化 (v2)

### 前端

- [x] 过滤栏
- [x] 多源对比视图
- [x] Dashboard
- [x] HistoryPanel

### 部署

- [ ] PostgreSQL Docker 部署
- [ ] 部署文档
- [ ] CI/CD
- [ ] Nginx 反向代理
- [ ] 域名和 HTTPS

---

## 设计决策记录

### 修正：Multi-Agent → Multi-Tool

- **之前**：多图+Supervisor（每个子模块作为独立Agent，有自己LLM）
- **现在**：Supervisor Agent（1个LLM）+ 5个 Tool Function
- **原因**：流程固定，子模块不需要自主决策，Supervisor作为中央调度器更可控

### JWT vs API Key

- **之前**：API Key 认证
- **现在**：JWT（access_token + refresh_token）
- **原因**：ToB场景需要多用户、团队管理、配额控制、token自动过期

### PPT 交付

- **方案**：只生成 JSON，前端渲染
- **原因**：避免引入 pptx 生成库的复杂度，JSON 可直接用 React 组件渲染

### 冲突检测

- **方案**：加入，但作为低优先级（不阻塞流程）
- **原因**：MVP 先跑通，冲突检测作为提示而非强制步骤