# 待讨论的功能 / 长期改进项

本文档记录暂不实现的功能点，等 MVP 跑通后再评估是否加入。

---

## 预设分析环节 (Preset)

**状态**: 待讨论

**描述**:

在 Planner Agent 中增加"预设分析"环节，在正式开始检索前输出：

- 分析范围和边界（如：基于公开新闻，不含企业内部数据）
- 可信来源优先级（如：官方博客 > 研究报告 > 新闻 > 社区）
- 已知的已知（已确认的事实）
- 已知的未知（已知但拿不到的数据，如企业内部信息）
- 分析截止时间

**触发条件**:
- 用户问"行业现状"、"市场分析"等需要大范围梳理的问题时
- 或者作为所有研究的默认前置步骤

**好处**:
- 减少幻觉：预设里说了"不含企业数据"，后面的 Agent 不会瞎编
- 缺口前置可见：主动说明数据局限性
- 报告更诚实：区分"有证据支撑"和"基于公开推断"

**坏处**:
- 增加 Planner 复杂度
- 预设不准会误导后续
- MVP 阶段可以先不加

**实现建议**:
- MVP 阶段不做预设
- 等报告质量不够、发现幻觉问题时再加
- 可以先在 prompt 里加一行"你没有企业内部数据，请在不确定时明确说明"

**相关文件**:
- `docs/deep-research-agent-design.md` — 已有提及

---

## 企业级可观测指标闭环

**状态**: 待实现

**面试价值**: 高。能体现从 demo 到生产系统的工程判断，但必须讲清楚"指标解决什么定位问题"，不能只说"接 Prometheus"。

**问题**:

当前 `metrics_registry` 是进程内计数器。单 worker demo 可以看到请求数量，但多 worker、重启、横向扩容后指标会丢，也无法回答关键生产问题：

- 是检索慢，还是 LLM 慢？
- Deep Research 平均消耗多少 token / 成本？
- 哪个 provider 失败率最高？
- unsupported citation 比例有没有下降？
- 任务失败集中在哪个阶段？

**反面质疑**:

如果只是把计数器换成 Prometheus，但没有 p95/p99、阶段耗时、错误分类和成本指标，这个改造没有工程含量，只是工具替换。

**建议方案**:

- 用 `prometheus_client` 替换进程内 counter。
- `/api/metrics` 输出标准 Prometheus 文本。
- 指标按阶段拆分：API、retrieval、rerank、LLM、research task。
- 记录低基数 label：`route`, `provider`, `status`, `stage`。不要把 `query`, `user_id`, `trace_id` 放进 label。
- dashboard 重点看 p50/p95/p99、错误率、token/cost、任务队列深度、citation unsupported rate。

**验收标准**:

- 服务重启后 Grafana 仍能看到历史趋势。
- 并发请求下能定位慢点属于 Milvus、Neo4j、reranker 还是 LLM。
- 每个 Deep Research task 能看到调用次数、耗时、token 和估算成本。
- unsupported citation rate 可以按版本对比。

**相关文件**:

- `backend/src/core/metrics.py`
- `backend/src/api/routes.py`
- `backend/src/agent/graph.py`
- `backend/src/agent/runtime.py`

---

## Deep Research / Ingest 任务队列化

**状态**: Deep Research 已完成第三阶段；Ingest 仍可复用同一队列模型继续改造

**面试价值**: 高。能体现对后台任务可靠性、恢复、重试、幂等的理解。

**问题**:

当前研究任务和导入任务主要靠 DB 状态 + `asyncio.create_task`。这适合 PoC，但生产里有几个硬风险：

- worker 重启后正在跑的任务会丢或变成 orphan。
- 多进程部署时内存里的 task 引用不可共享。
- 无法做可靠 retry、dead letter、heartbeat。
- 任务取消依赖轮询 DB 状态，延迟和一致性都弱。
- 高并发 research 会挤爆 LLM API 额度和本机资源。

**反面质疑**:

直接上 Celery 也不等于企业级。如果没有幂等 key、任务状态机、超时、重试边界和恢复策略，只是把问题从 FastAPI 进程搬到 worker 进程。

**已完成**:

- 新增 `backend/src/tasks/reliable.py`：可靠任务状态机，覆盖 enqueue、reserve、heartbeat、retry、cancel、dead letter、stale running reclaim。
- 新增 `backend/src/tasks/research.py`：Deep Research DB-backed durable queue，数据库是任务状态和审计的 source of truth。
- 新增 `backend/scripts/run_research_worker.py`：独立 worker 入口，API 进程不再直接 `asyncio.create_task` 执行长任务。
- `POST /api/research` 改为创建 `pending` 任务并入队；worker 领取后置为 `running`。
- `cancel` 改为 `cancelled + cancel_requested_at`，worker 在 heartbeat/step callback 中协作式停止。
- 失败任务根据 `attempt_count/max_attempts` 自动回到 `pending` 重试，超过上限进入 `dead_letter`。
- 启动恢复逻辑从“orphaned running 标 failed”改成“stale running 重新入队”，避免 worker 重启导致长任务静默丢失。
- 新增 `004_reliable_research_tasks.sql` 迁移：`attempt_count/max_attempts/locked_by/heartbeat_at/cancel_requested_at/dead_letter_reason`。

**后续建议方案**:

- 接真实 Redis broker 作为 wake-up queue / delayed retry 调度层；当前实现已把 DB durable state 和 worker state machine 做好。
- 将 Ingest 任务复用同一 `tasks` 状态机。
- API 只创建 `research_tasks` 记录并投递 job。
- Worker 消费 job，按阶段写 progress/event。
- 任务有 `pending/running/completed/failed/cancelled/dead_letter` 状态机。
- 每个任务记录 heartbeat、attempt_count、worker lease、dead_letter_reason。
- 按租户和全局配置并发上限。

**验收标准**:

- kill worker 后任务不会静默消失。
- 重启 worker 后 pending 任务可继续，stale running 任务可恢复或标记 failed。
- 同一个 task_id 不会重复执行两次。
- LLM provider 429 时按 retry policy 退避，不会无限重试。
- 取消任务后 worker 最多一个阶段内停止。

**相关文件**:

- `backend/src/api/research.py`
- `backend/src/api/routes.py`
- `backend/src/agent/research_graph.py`
- `backend/src/db/models.py`
- `backend/src/tasks/reliable.py`
- `backend/src/tasks/research.py`
- `backend/scripts/run_research_worker.py`
- `backend/migrations/004_reliable_research_tasks.sql`

---

## 检索质量与 Badcase 回归闭环

**状态**: 部分实现

**面试价值**: 最高。RAG 面试里最能区分"会搭系统"和"会做质量工程"。

**问题**:

项目已有评测脚本和 FinanceBench 数据，但还没有形成持续闭环。现在仍然容易陷入：

- 只凭主观体验判断回答好坏。
- 改 prompt / reranker / RRF 权重后不知道质量是否退化。
- 用户点踩没有进入 badcase 回归。
- 检索指标和生成指标没有绑定到版本。

**反面质疑**:

LLM-as-Judge 不是万能评测。只用 Judge 分数没有 gold evidence、没有人工 badcase、没有分层统计，面试官会认为你只是套了评测名词。

**已完成**:

- 新增 `eval.datasets`，统一加载 JSON / JSONL golden set 和 badcase。
- `build_financebench_eval.py` 输出的 `doc_name` 会被评测 loader 自动映射为 `expected_sources`。
- `evaluate_retrieval.py` 在原有 `Precision@K / Recall@K / NDCG@K` 基础上新增 `Source Recall@5`。
- 新增 badcase regression summary：统计 badcase 总数、修复数、修复率、失败 case id。
- 检索质量门禁从单一 `Precision@5` 升级为 `Precision@5 + Source Recall@5 + Badcase Fix Rate`。
- 新增 `backend/data/eval/README.md` 和 `badcases.example.jsonl`，明确人工 badcase 的落库格式。

**后续建议方案**:

- 建立 golden set：FinanceBench + 人工金融查询 + 中文多跳问题。
- 每条样本包含 `query`, `expected_sources`, `gold_answer`, `difficulty`, `category`。
- 检索层评估 `Precision@K`, `Recall@K`, `NDCG@K`, `MRR`。
- 生成层评估 faithfulness、citation coverage、correctness、unsupported claim rate。
- 线上 negative feedback 进入 badcase 候选，人工审核后加入回归集。
- 每次改 retrieval/prompt/reranker 都跑 smoke eval，每晚跑 full eval。

**验收标准**:

- 能比较 `semantic only`、`hybrid RRF`、`hybrid + reranker` 三种方案。
- badcase 集合里的错误不会在下一版重复出现。
- 指标按 easy/medium/hard 和 query type 分层。
- 每个答案能追溯到 prompt version、model、retrieval results、trace_id。

**相关文件**:

- `backend/scripts/evaluate_retrieval.py`
- `backend/scripts/evaluate_e2e.py`
- `backend/scripts/build_financebench_eval.py`
- `backend/src/eval/datasets.py`
- `backend/src/eval/metrics.py`
- `backend/src/eval/judge.py`
- `backend/data/eval/README.md`
- `backend/src/agent/nodes.py`
- `backend/src/retrieval/retriever.py`

---

## 外部服务压测与故障注入

**状态**: 第四阶段骨架已完成，真实容量数字待在目标机器压测补齐

**面试价值**: 高。适合回答"你怎么证明 4 核 / 15.6GB 能跑 10 万到 100 万文档"。

**问题**:

系统依赖 DeepSeek/OpenAI/Qwen、火山 embedding、Milvus、Neo4j、PostgreSQL、MinIO、Feishu、RSS 等外部服务。之前主要验证了单元测试和 mock 流程，还不能证明真实外部依赖故障下的系统表现。

第四阶段已经先补齐工程骨架：

- `DegradationPolicy` 统一定义 Graph、LLM、Milvus、worker 的降级 / 失败策略。
- `FaultInjector` 支持通过 env 或 `X-Fault-Injection` header 注入 `graph:timeout`、`llm:timeout`、`milvus:down` 等故障。
- Retriever 接入 Graph 故障降级：Neo4j/Graph path 失败时记录 `rag_degradation_events_total`，hybrid 查询继续使用 semantic / keyword / title。
- Locust 覆盖普通 query、SSE query、Deep Research enqueue 三类场景。
- `generate_capacity_report.py` 可把 Locust JSON summary 转成容量报告，识别 p95 和错误率瓶颈。

**反面质疑**:

不要说"我做了压测"但拿不出场景、指标和瓶颈。压测如果不能回答 p95、错误率、队列深度、资源瓶颈，就只是跑了一次脚本。

**建议方案**:

- 用 Locust 建立三类场景：普通 query、SSE query、Deep Research task enqueue。
- 用故障注入覆盖：LLM 429/timeout、embedding timeout、Milvus down、Neo4j down、worker slow/kill、SSE client disconnect。
- 每类故障定义降级策略：Graph fallback vector、LLM evidence-only / fail-fast、Milvus hard fail、worker retry / dead letter。
- 压测报告记录 CPU、内存、DB 连接池、Milvus latency、LLM latency、degradation events、dead letter 增长。

**验收标准**:

- 100 并发普通查询下能给出 p95 和错误率。
- Neo4j 挂掉时 hybrid query 可降级到 vector/keyword/title，并记录 `rag_degradation_events_total`。
- LLM timeout 不会拖死 FastAPI event loop，并能被故障注入稳定复现。
- SSE 客户端断开后后端能停止无意义生成或正确记录取消。
- Worker 被 kill 后任务状态可恢复、重试或进入 dead letter。
- 容量报告能明确第一瓶颈，而不是只给"压测通过"结论。

**相关文件**:

- `backend/src/retrieval/retriever.py`
- `backend/src/agent/runtime.py`
- `backend/src/core/degradation.py`
- `backend/src/core/fault_injection.py`
- `backend/src/agent/research_graph.py`
- `backend/src/api/research.py`
- `backend/loadtests/locustfile.py`
- `backend/scripts/generate_capacity_report.py`
- `docs/capacity-report-template.md`

---

## Agent 成本控制与部分报告

**状态**: 第五阶段第一版已完成，进程内 usage ledger 可用；企业账单级持久化待补

**面试价值**: 高。适合回答"Agent 怎么避免无限规划、无限调用、成本失控"。

**问题**:

长链路 Agent 的风险不是一次 LLM 调用，而是 analyze / evaluate / writer / self-reflect / Deep Research 多阶段叠加后，token 和美元成本不可控。只限制 `max_tool_calls` 不够，因为一次超长上下文调用也可能直接打穿预算。

第五阶段已经先补齐工程骨架：

- `UsageTracker` 记录每次 LLM 调用的 `trace_id/company_id/user_id/provider/model/operation/prompt_tokens/completion_tokens/estimated_cost_usd`。
- `BudgetPolicy` 支持请求级 token 预算和美元成本预算；可以配置为只追踪不拦截。
- `BudgetedLLM` 包装非流式和流式 LLM 调用：调用前做预算预检，调用后记录 usage；流式生成超预算时停止继续消费并输出 `[partial report]`。
- Agent answer 节点识别 `BudgetExceeded`，返回基于已有 evidence 的部分报告，而不是普通生成失败。
- 新增 `/api/cost/dashboard`，按当前租户返回总请求数、token、估算成本、partial report 数、按模型 / operation 分组和最近调用。
- Prometheus 指标新增 `rag_usage_requests_total`、`rag_usage_tokens_total`、`rag_usage_cost_usd_total`、`rag_budget_exceeded_total`。

**反面质疑**:

不要把进程内 usage tracker 说成企业计费系统。多 worker、重启、横向扩容后，当前账本仍会丢；真实生产要落 Postgres/ClickHouse/Redis Stream，并做价格表版本化。

**建议方案**:

- 请求级预算：普通 query 设置较低 token / cost 上限，Deep Research task 设置更高但有限的预算。
- 租户级预算：按 company_id 做日 / 月累计预算，接近阈值时降级模型或只返回 evidence-only。
- 任务级预算：Deep Research 每个 task 记录 `llm_calls/tokens/cost/elapsed_seconds`，超预算后停止后续 planner/writer 调用。
- 成本看板：按 provider/model/operation/company 统计成本，定位最贵路径。
- 部分报告：预算耗尽时输出已有证据、已覆盖问题、未覆盖问题和下一步建议。

**验收标准**:

- 单次 query prompt 过大时不会继续调用 LLM。
- 流式回答超预算后停止继续生成，并向用户返回 partial report。
- `/api/cost/dashboard` 能按租户展示 token、估算成本、partial report 次数。
- metrics 能看到预算超限次数和不同模型的 usage。
- Deep Research 后续接入后，每个 task 能看到累计成本并在超预算时停止。

**相关文件**:

- `backend/src/core/cost_control.py`
- `backend/src/agent/runtime.py`
- `backend/src/agent/nodes.py`
- `backend/src/api/routes.py`
- `backend/tests/test_cost_control_p5.py`

---

## LLM / Deep Research 成本预算与熔断

**状态**: 待实现

**面试价值**: 中高。适合体现金融 Agent 长任务的成本意识。

**问题**:

Deep Research 是长链路任务，Planner / Retriever / Analyst / Checker / Writer 多轮调用 LLM。如果没有预算控制，用户一个复杂问题可能触发大量 LLM 调用，带来成本和延迟失控。

**反面质疑**:

只设置 `max_tool_calls=20` 不够。工具调用次数不等于 token 成本，某次 writer 生成长报告可能比多次小调用更贵。

**建议方案**:

- 每个 task 记录 `llm_call_count`, `prompt_tokens`, `completion_tokens`, `estimated_cost`。
- 设置 per-task 成本上限和时间上限。
- Checker 补检循环同时受 tool call、成本、时间三重约束。
- provider 429 或预算耗尽时，Writer 输出"基于已有证据的部分报告 + 缺口说明"。
- 按租户配置月度预算和单任务预算。

**验收标准**:

- 每个 research task 能在结果里看到成本摘要。
- 超预算任务不会继续调用 LLM。
- 报告能明确说明哪些结论因预算/证据不足未覆盖。
- dashboard 能按租户统计 LLM 花费。

**相关文件**:

- `backend/src/llm/client.py`
- `backend/src/agent/research_graph.py`
- `backend/src/agent/research_memory.py`
- `backend/src/db/models.py`
- `backend/src/core/metrics.py`
