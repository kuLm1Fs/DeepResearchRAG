# RAG News Intelligence — 技术债与已知问题

> 最后更新: 2026-05-31

本文档记录代码审计中发现的技术债，分为「已修复」和「待处理」两部分。

---

## 已修复

### Phase 1: 安全加固

| # | 问题 | 修复方案 | 涉及文件 |
|---|------|----------|----------|
| P1-1 | SSE endpoint 通过 URL query 参数传 JWT，token 泄露在日志/浏览器历史 | 改用 `fetch()` + `ReadableStream`，通过 `Authorization` header 传 token | `research.py`, `client.ts`, `ResearchPanel.tsx` |
| P1-2 | `ingest_tasks` dict 和 `_cancelled_tasks` set 是进程级变量，gunicorn 多 worker 下跨 worker 不可见 | ingest tasks 迁移到 PostgreSQL (`IngestTask` 模型)；research 取消改为查询 DB status | `routes.py`, `models.py`, `research.py`, `research_graph.py` |
| P1-3 | `.env` 文件弱密码、拼接错误、硬编码 IP | 替换为占位符，修复拼接，IP 改 localhost | `configs/.env`, `configs/.env.dev` |
| P1-4 | `industry_collection.py` Milvus 表达式 f-string 拼接存在注入风险 | 添加 `_escape_milvus_str()` 转义函数 | `industry_collection.py` |
| P1-5 | docker-compose 硬编码密码、内部端口暴露、无重启策略、无资源限制 | 密钥外部化、端口绑定 127.0.0.1、添加 restart policy 和 memory limits | `docker/docker-compose.yml` |
| P1-6 | JWT secret 无最小长度校验 | 添加 `model_validator` 校验 ≥32 字符（prod） | `core/config.py` |
| P1-7 | Dockerfile 安全问题：root 运行、版本未 pin、权限过宽 | 非 root 用户、pin uv 版本、收紧 chmod、entrypoint.sh +x | `backend/Dockerfile`, `frontend/Dockerfile` |

### Phase 2: 代码质量

| # | 问题 | 修复方案 | 涉及文件 |
|---|------|----------|----------|
| P2-1 | DeepSeek/OpenAI/Qwen 三个 LLM 类几乎相同 | 合并为 `OpenAICompatibleLLM`，通过 `base_url` 配置 | `llm/client.py` |
| P2-2 | `DIM` 和 `get_milvus_connection()` 在三个文件中重复定义 | 提取到 `_common.py` 共享模块 | `vectorstore/_common.py` |
| P2-3 | Pipeline 创建后不关闭，FeishuCollector 的 httpx.Client 泄漏 | `FeishuCollector` 添加 `close()`；`Pipeline.shutdown()` 关闭所有 collector；routes.py 用 try/finally | `feishu_collector.py`, `pipeline.py`, `routes.py` |
| P2-4 | 前端 `query()` 复制了 `fetchWithErrorHandling` 的全部 401 刷新逻辑 | 提取 `fetchWithAuth()` 为单点 auth + 401 重试；提取 `storeAuthTokens()` | `client.ts` |

### Phase 3: CRITICAL 问题修复

| # | 问题 | 修复方案 | 涉及文件 |
|---|------|----------|----------|
| P3-1 | `decode_token()` 不验签且公开可导入，误用即可伪造 JWT | 删除该函数 | `auth/jwt_handler.py`, `auth/__init__.py` |
| P3-2 | `IndustryCollection` 无 `company_id` 字段；research retriever 传 `filters=None` 跳过租户隔离 | schema 添加 `company_id`；`aretriever` 接受并传递 tenant filters | `industry_collection.py`, `research_tools.py`, `research_graph.py` |
| P3-3 | research task 用 `asyncio.create_task` 不存引用，GC 时任务丢失；worker 重启后无恢复 | 添加 `_active_tasks` set 跟踪；启动时回收 orphaned tasks | `research.py`, `app.py` |

### Phase 4: Agent 调用链生产就绪

| # | 问题 | 修复方案 | 涉及文件 |
|---|------|----------|----------|
| A1 | LLM 调用无重试、无超时 | tenacity 3 次指数退避重试（429/500/502/503/Timeout）；AsyncOpenAI timeout=60s；stream_chat try/finally 关闭 | `llm/client.py` |
| A2 | pymilvus 同步调用阻塞 event loop | 添加 `search_async`/`query_async`/`insert_async` 用 `asyncio.to_thread()` 包装 | `vectorstore/milvus_store.py` |
| A3 | `self_reflect` quality_map 映射反了 | 反转映射：0→EXCELLENT, 3→POOR | `agent/nodes.py` |
| A4 | research task 无并发限制 | 创建前查 running 任务数，≥3 返回 429 | `api/research.py` |
| A5 | 三路检索顺序执行 | `asyncio.gather` 并行语义/关键词/标题三路 | `retrieval/retriever.py` |
| A6 | 每次请求重建 LLM client / Retriever | 模块级单例缓存 `_cached_llm` 和 `_cached_retriever` | `agent/research_tools.py` |
| A7 | 非流式路径无错误处理 | try/except 包裹 `run_agent()`，返回 SSE error event | `api/routes.py` |
| A8 | 流式中断错误混在正文 | re-raise 异常由调用方处理，不再 yield 错误文本 | `agent/nodes.py` |

---

## 待处理

### HIGH

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| H1 | `/api/metrics` 无认证无限流，暴露内部计数器 | `routes.py:530` | 添加 `Depends(get_current_user)` 或内网 IP 白名单 |
| H2 | SSE research event stream 每秒轮询 DB 无超时上限 | `research.py:270` | 添加最大连接时长（如 30 分钟），添加 rate limit |
| H3 | `compiled_graph` 全局变量懒初始化非线程安全 | `graph.py:218` | 改用 `threading.Lock` 或模块级 `compile()` |
| H4 | `Content-Length` 非整数时 `int()` 抛 ValueError → 500 | `middleware.py:55` | try/except 包裹，返回 400 |
| H5 | health check 每次新建 MilvusStore + load collection | `routes.py:304` | 复用单例或缓存连接，health check 用轻量 ping |
| H6 | 注册只检查密码 ≥8 字符，无复杂度要求 | `models.py:109` | 添加正则校验（大写+数字+特殊字符） |
| H7 | 无修改密码端点，无 refresh token 批量吊销 | `auth.py` | 实现 change-password 端点 + 级联吊销 |
| H8 | `/stats` 查询 10000 条全量记录到内存做统计 | `routes.py:250` | 改用 Milvus aggregation 或独立 stats 表 |

### MEDIUM

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| M1 | TraceIDMiddleware 对 health check 也打 INFO 日志 | `middleware.py:22` | 跳过 `/health`, `/readyz`, `/livez`, `/metrics` |
| M2 | `datetime.utcnow()` 已废弃 (Python 3.12+) | `auth.py:49` | 改用 `datetime.now(timezone.utc)` |
| M3 | `research_tools.py` 中 5 个 sync wrapper 是死代码 | `research_tools.py` | 删除 sync wrapper，只保留 async 版本 |
| M4 | `ingest_trigger` 返回 200 + `status="error"` 而非 HTTP 错误码 | `routes.py:424` | 改为 `raise HTTPException` |
| M5 | ChatWindow 用 `key={idx}` 渲染消息列表 | `ChatWindow.tsx:232` | 给 message 添加唯一 ID |
| M6 | MetricsRegistry 进程内计数，worker 重启归零 | `metrics.py` | 考虑 Prometheus client 或 Redis 计数 |
| M7 | 每个请求新建 Pipeline + MilvusStore，连接开销大 | `routes.py` 多处 | 考虑连接池或单例 |
| M8 | `ingest_status` 的 `total` 被 limit=1000 截断 | `routes.py:506` | 使用 `MilvusStore.count()` 获取真实总数 |
| M9 | research 与 ingest 的 company 访问控制不一致 | `research.py:181` | 统一访问控制策略 |
| M13 | `ingest_task_list` OR 查询在 company_id 为空时可能泄露 | `routes.py:465` | 添加 `company_id != ""` 条件 |

### LOW

| # | 问题 | 位置 | 建议 |
|---|------|------|------|
| L1 | `_error_analyst` 等多个函数从未调用 | `research_tools.py` | 删除 |
| L2 | `ingest_tasks` 表缺 `created_at` 索引 | `models.py:152` | 迁移脚本添加索引 |
| L3 | `ChunkStore` 导出但未在生产代码中使用 | `vectorstore/__init__.py` | 确认是否需要，不需要则移除 |
| L4 | 前端 SSE 忽略 `error`/`done` 事件 | `client.ts:224` | 处理 error 事件，通知用户 |
| L5 | API key 三重检查重复 4 次 | `research_tools.py` | 提取为 helper 函数 |
| L6 | `IndustryCollection.insert` 返回值不明确 | `industry_collection.py:152` | 改为显式 `result.primary_keys` |
| L7 | `debug` 默认 `True` | `config.py:28` | 改为 `False` |
| L8 | `frontend/dist/` 提交到 git | `frontend/dist/` | 添加到 `.gitignore` |
| L9 | 生产环境 `/docs` 和 `/openapi.json` 未关闭 | `app.py` | prod 环境设置 `docs_url=None` |
| L10 | `embed_texts_async` 用 tqdm 写 stderr | `embedding.py:56` | 改用 structlog |

---

## Agent 调用链生产就绪评估

### 问题与方案

#### A1. LLM 调用无重试、无超时 `llm/client.py`

**问题**：`chat()` 单次 API 调用，429/500/超时直接抛异常。embedding 模块有 tenacity 3 次重试，LLM 反而没有。`AsyncOpenAI` 未配置 timeout（默认 10 分钟）。

**方案**：
- 给 `chat()` 和 `stream_chat()` 加 tenacity 重试（3 次，指数退避 1-10s），只对可重试异常（429、500、502、503、Timeout）重试
- `AsyncOpenAI` 初始化加 `timeout=60.0`（单次请求 60s）
- `stream_chat` 用 `async with` 确保 stream 关闭

**可行性**：高。改动集中在 `llm/client.py` 一个文件，tenacity 已在项目依赖中（embedding 用了）。不影响调用方接口。

**状态**：已修复 ✅

---

#### A2. pymilvus 同步调用阻塞 event loop `retrieval/retriever.py`

**问题**：`MilvusStore.search()`、`query()`、`insert()` 是 pymilvus 同步调用，在 async 函数里直接调用会阻塞整个 event loop。并发请求退化为串行。

**方案**：用 `asyncio.to_thread()` 包装同步调用。在 `MilvusStore` 中添加 async 方法（`search_async`、`query_async`），内部调 `to_thread(self.search, ...)`。retriever 改用 async 版本。

**可行性**：高。`asyncio.to_thread` 是 Python 3.9+ 标准库，无额外依赖。改动限于 `milvus_store.py` + `retriever.py`。pymilvus 连接是线程安全的（全局 registry）。

**状态**：已修复 ✅

---

#### A3. `self_reflect` quality_map 映射反了 `nodes.py:586`

**问题**：`{0: "POOR", 1: "FAIR", 2: "GOOD", 3: "EXCELLENT"}` — 0 issue 映射到 POOR，3+ issue 映射到 EXCELLENT。逻辑反转。

**方案**：反转映射 `{0: "EXCELLENT", 1: "GOOD", 2: "FAIR", 3: "POOR"}`。

**可行性**：极高。一行改动，无副作用。

**状态**：已修复 ✅

---

#### A4. research task 无并发限制 `research.py`

**问题**：可无限创建 research task，每个最多 20 轮 × 3 次 LLM 调用 = 60+ 次 API 调用。无限制会耗尽 API 额度和内存。

**方案**：在 `create_research_task` 中检查当前 running 状态的任务数，超过阈值（如 3）返回 429。

**可行性**：高。一次 DB count 查询，无架构变更。

**状态**：已修复 ✅

---

#### A5. 三路检索顺序执行 `retriever.py`

**问题**：语义搜索、关键词搜索、标题匹配串行执行，每次查询 3 次 Milvus round-trip。

**方案**：用 `asyncio.gather` 并行执行三路检索。

**可行性**：高。需要先把 A2（async 包装）做完。三路检索之间无数据依赖。

**状态**：已修复 ✅（依赖 A2）

---

#### A6. 每次请求重建 LLM client / Retriever `research_tools.py`

**问题**：`_create_research_llm()` 每次调用新建 `AsyncOpenAI`，连接泄漏。`aretriever` 每次新建 `MultiPathRetriever`，reranker 模型重复加载。

**方案**：模块级单例缓存 LLM client 和 Retriever。

**可行性**：高。需要在 shutdown 时 close client（`BaseLLM.close()` 已有）。

**状态**：已修复 ✅

---

#### A7. 非流式路径无错误处理 `routes.py:218`

**问题**：`run_agent()` 抛异常时直接 500，无结构化错误响应。

**方案**：加 try/except，返回 SSE error event。

**可行性**：极高。

**状态**：已修复 ✅

---

#### A8. SSE 流式中断错误混在正文 `nodes.py:657`

**问题**：stream 中断时 yield `"\n\n[生成中断，请重试]"`，混在正常文本中，前端无法区分。

**方案**：yield 结构化 error event（`{"type": "error", ...}`），不在 content 流中混入错误文本。

**可行性**：高。

**状态**：已修复 ✅

---

### 修复顺序

| 顺序 | 任务 | 理由 | 状态 |
|------|------|------|------|
| 1 | A3 quality_map bug | 一行修复，立即消除错误行为 | ✅ |
| 2 | A1 LLM 重试+超时 | 最高 ROI，直接减少用户可见错误 | ✅ |
| 3 | A7 非流式错误处理 | 简单但影响用户体验 | ✅ |
| 4 | A2 Milvus async 包装 | 性能瓶颈，A5 的前置条件 | ✅ |
| 5 | A5 三路检索并行 | 依赖 A2，完成后检索延迟降 ~3x | ✅ |
| 6 | A4 research 并发限制 | 防护性措施 | ✅ |
| 7 | A6 client 单例缓存 | 减少连接泄漏 | ✅ |
| 8 | A8 流式错误事件 | 体验优化 | ✅ |
