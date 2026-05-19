# Issues

## 现有问题

### Issue 1: jwt_secret_key vs jwt_secret 配置字段名不一致

- **文件**: `backend/src/auth/jwt_handler.py` 和 `backend/src/core/config.py`
- **问题**: `jwt_handler.py` 使用 `settings.jwt_secret`，但 Task Card 测试期望 `settings.jwt_secret_key`
- **影响**: 配置字段命名不一致，但功能正常
- **修复建议**: 统一字段名为 `jwt_secret`（已存在）或 `jwt_secret_key`（更明确）
- **状态**: ⏳ 待确认命名规范

### Issue 2: JWT 测试需要 JWT_SECRET 环境变量

- **文件**: `backend/src/core/config.py`
- **问题**: `_get_jwt_secret()` 要求 `JWT_SECRET` 必须设置，否则 `create_access_token` 会抛出 `ConfigError`
- **影响**: 在没有 `.env.dev` 或未设置环境变量的环境下，JWT 功能无法测试
- **修复建议**: 开发环境提供默认 JWT_SECRET（仅用于本地开发）
- **状态**: ⏳ 待修复

---

## 登录功能调试记录（2026-05-14）

### Issue 3: asyncpg 未安装

- **文件**: `backend/pyproject.toml` + 运行环境
- **问题**: `ModuleNotFoundError: No module named 'asyncpg'`
- **原因**: `pyproject.toml` 缺少 asyncpg 依赖
- **修复**: 添加到 `pyproject.toml`：`asyncpg>=0.29.0`
- **状态**: ✅ 已修复（b726e3a 同时添加了 asyncpg + greenlet + sqlalchemy[asyncio]）

### Issue 4: greenlet 未安装

- **文件**: `backend/pyproject.toml`
- **问题**: `No module named 'greenlet'`（SQLAlchemy asyncio 需要）
- **修复**: 添加 `greenlet>=3.0.0` 到依赖
- **状态**: ✅ 已修复

### Issue 5: PostgreSQL 连接地址配置错误

- **文件**: `backend/configs/.env.dev`
- **问题**: 后端从 Mac 连远程 postgres 用的是 `localhost`，但远程只暴露了公网 IP `117.72.164.6`
- **影响**: `ConnectionRefusedError: [Errno 61]`
- **修复**: 本地 Mac 启动后端时指定 `POSTGRES_HOST=117.72.164.6`
- **状态**: ✅ 已修复（但建议远程后端用 `POSTGRES_HOST=localhost` 更安全）

### Issue 6: pg_hba.conf 认证规则顺序错误

- **文件**: 远程服务器 docker postgres 容器内 `pg_hba.conf`
- **问题**: `host all all all md5` 放在前面，远程 TCP 连接都被 md5 拦住
- **影响**: Navicat 和 Python 后端无法通过 TCP 认证（本地 socket 可以）
- **修复**: 删除 `host all all all md5` 这行，或将其移到 trust 规则之后
- **状态**: ✅ 已修复

### Issue 7: models.py 使用 `default=func.now()` 而非 `server_default`

- **文件**: `backend/src/db/models.py`
- **问题**: asyncpg 不接受 SQLAlchemy 的 `func.now()` / `func.current_date` 作为 Python 端的 default 参数
- **现象**: `Neither 'current_date' object nor 'Comparator' object has attribute 'toordinal'`
- **修复**: 所有 `default=func.now()` 改为 `server_default=func.now()`，`default=func.current_date` 改为 `server_default=text("CURRENT_DATE")`
- **状态**: ✅ 已修复（commit b726e3a）

### Issue 8: bcrypt 无法哈希 JWT refresh_token（72字节限制）

- **文件**: `backend/src/api/auth.py`
- **问题**: bcrypt 有 72 字节限制，JWT refresh_token 字符串几百字节
- **现象**: `ValueError: password cannot be longer than 72 bytes`
- **修复**: refresh_token 改用 SHA256 哈希（JWT 本身已签名，只需防泄露）
- **状态**: ✅ 已修复（commit 03c3241）

### Issue 9: timezone-aware 和 timezone-naive datetime 混用

- **文件**: `backend/src/api/auth.py`
- **问题**: 数据库字段是 TIMESTAMP WITHOUT TIME ZONE，但代码用 `datetime.now(timezone.utc)`
- **现象**: `can't subtract offset-naive and offset-aware datetimes`
- **修复**: 统一用 `datetime.utcnow()` 替代 `datetime.now(timezone.utc)`
- **状态**: ✅ 已修复（commit 0874694）

---

## 历史 Issues（已修复）

### Issue N: jwt_handler.py 缺少 decode_access_token 函数

- **状态**: ✅ 已修复（在 c71b688 之后）
- **修复**: CC 添加 `decode_access_token` 函数

---

## Agent 编排审计记录（2026-05-19）

### Issue 10: 流式与非流式 Agent 编排路径不一致

- **文件**: `backend/src/agent/graph.py`
- **问题**: 非流式路径走 LangGraph，流式路径手工串联节点，且流式缺少检索质量评估、补检索、多源对比等步骤
- **影响**: 同一个查询在 `stream=true/false` 下可能得到不同检索材料和不同质量控制结果
- **修复**: 新增共享的 pre-generation 编排流程，流式输出在生成 token 前执行同样的分析、规划、检索、评估、补检索和多源对比
- **状态**: ✅ 已修复

### Issue 11: `compare_sources` 节点执行顺序错误

- **文件**: `backend/src/agent/graph.py`
- **问题**: 多源对比节点原先在检索前执行，状态中还没有 `retrieval_results`
- **影响**: 多源对比功能表面存在，实际无法工作
- **修复**: 将 `compare_sources` 移到检索质量评估和补检索之后、答案生成之前
- **状态**: ✅ 已修复

### Issue 12: `reflection` 字段混用导致状态语义不清

- **文件**: `backend/src/agent/state.py`, `backend/src/agent/nodes.py`
- **问题**: 检索质量评估和答案自检都写入 `reflection`
- **影响**: 路由决策、答案质量评估和调试观测互相覆盖
- **修复**: 拆分为 `retrieval_evaluation` 和 `answer_reflection`，保留 `reflection` 作为兼容别名
- **状态**: ✅ 已修复

### Issue 13: LLM JSON 输出解析过于脆弱

- **文件**: `backend/src/agent/nodes.py`, `backend/src/agent/research_tools.py`
- **问题**: 直接 `json.loads(response.strip())`，遇到 markdown code block 或前置说明会失败
- **影响**: Agent 控制流容易误入 fallback，降低检索规划和质量评估稳定性
- **修复**: 新增统一 JSON object 提取函数，并复用于普通 RAG Agent 和 Deep Research tools
- **状态**: ✅ 已修复

### Issue 14: 顶层 `import agent` 会被 Deep Research 相对导入破坏

- **文件**: `backend/src/agent/research_graph.py`, `backend/src/agent/research_tools.py`
- **问题**: `agent.__init__` 导入 research 模块时，`from ..core` 等相对导入会在顶层包导入场景下报错
- **影响**: `/api/query` 中 `from agent import run_agent` 存在启动期失败风险
- **修复**: research 模块改为与现有普通 RAG Agent 一致的绝对导入风格
- **状态**: ✅ 已修复

### Issue 15: Deep Research Planner 子问题没有传给 Retriever

- **文件**: `backend/src/agent/research_graph.py`
- **问题**: Planner 返回 `sub_questions`，但 graph state 没有更新该字段
- **影响**: Retriever 实际只检索原始 query，研究计划形同虚设
- **修复**: 新增 planner node，将 `sub_questions` / `research_questions` 提升到 state
- **状态**: ✅ 已修复

### Issue 16: Deep Research Checker 被重复调用

- **文件**: `backend/src/agent/research_graph.py`
- **问题**: checker 节点 lambda 中 `_call_checker(state)` 执行两次
- **影响**: 额外消耗 LLM token，且两次结果可能不一致
- **修复**: 新增 checker node，单次调用后同时写入 `check_result`、`gaps` 和 `conflicts`
- **状态**: ✅ 已修复

### Issue 17: Deep Research 补检索可能重复拉同一批材料

- **文件**: `backend/src/agent/research_graph.py`
- **问题**: Checker 发现 gaps 后重新进入 Retriever，但 Retriever 仍可能使用原始子问题，且新证据覆盖旧证据
- **影响**: 可能浪费工具调用，并丢失第一轮证据
- **修复**: 补检索时优先使用 `gaps` 作为查询，并合并/去重新旧 evidence
- **状态**: ✅ 已修复

### Issue 18: Deep Research 缺少真正的生产级运行时抽象

- **文件**: `backend/src/agent/*`
- **问题**: LLM、Retriever、MilvusStore、settings 仍在节点内部直接创建或调用
- **影响**: 单测需要大量 patch，生产上难以做超时、熔断、灰度、provider fallback 和成本统计
- **修复**: 已为普通 RAG Agent 新增 `AgentRuntime`，支持注入 LLM、Retriever 和答案缓存包装；Deep Research 仍需进一步接入统一 runtime
- **状态**: ✅ 普通 RAG Agent 已修复；Deep Research runtime 注入待后续收敛

### Issue 19: Deep Research 工具仍使用同步包装调用异步 LLM

- **文件**: `backend/src/agent/research_tools.py`
- **问题**: `_call_*` 包装中使用 `asyncio.run()` 调用 async LLM
- **影响**: 如果未来这些工具直接在 FastAPI async event loop 中调用，可能触发 nested event loop 错误
- **修复**: 新增 async-first tool API（`aplanner` / `aanalyst` / `achecker` / `awriter`），Research Graph 节点改为 async node；同步包装仅保留给非 async 外部调用兼容
- **状态**: ✅ 已修复

### Issue 20: 答案引用缺少 groundedness 校验

- **文件**: `backend/src/agent/nodes.py`
- **问题**: 当前 `self_reflect` 主要用长度、来源数量和标题关键词做启发式检查
- **影响**: 不能可靠判断答案中的关键 claims 是否被 sources 支撑
- **修复**: 增加轻量 claim splitting + lexical support check，`answer_reflection.unsupported_claims` 会输出弱支撑断言
- **状态**: ✅ 已修复（后续可升级为 LLM/NLI 级别 entailment）

### Issue 21: Agent 缺少节点级结构化 trace

- **文件**: `backend/src/agent/graph.py`
- **问题**: 线上出问题时只能看散落日志，无法稳定知道每个节点的执行顺序、耗时、输出摘要和失败节点
- **影响**: 难以定位问题发生在 query analysis、retrieval、re-search、generation 还是 reflection
- **修复**: 为普通 RAG Agent 增加 `node_traces`，每个节点记录 `node`、`status`、`error_level`、`duration_ms`、紧凑输出摘要和基础成本/规模指标；流式共享编排和 LangGraph 节点都接入 trace wrapper
- **为什么做**: Agent 的线上问题通常不是“最终报错”这么简单，而是某个中间节点输出为空、耗时异常、误触发 fallback 或检索结果规模异常。只有最终 answer 和散落日志，很难复盘一次执行链路。
- **怎么实现**:
  - 在 `run_traced_node()` 里统一包裹节点执行。
  - 成功时写入 `node_traces`，包含节点名、状态、耗时、输出摘要和 metrics。
  - 失败或 fallback 时同样写入 trace，保证异常链路也可回放。
  - `summarize_node_output()` 只记录列表数量和 dict keys，避免把大段正文或敏感内容塞进 trace。
- **代码位置**:
  - `backend/src/agent/graph.py`：`run_traced_node()`、`traced_node()`、`summarize_node_output()`。
  - `backend/src/agent/runtime.py`：`AgentRuntime.trace_metrics()`。
  - `backend/tests/test_agent_orchestration.py`：trace 顺序和 metrics 回归测试。
- **运行时行为**:
  - 普通 LangGraph 路径每个节点都会追加一条 trace。
  - 流式路径的 pre-generation 编排同样会记录 trace。
  - retrieve 节点会记录 `retrieval_results_count` / `filtered_results_count`。
  - answer/reflection 相关节点会记录 `answer_chars` / `unsupported_claims_count` 等指标。
- **面试怎么讲**: “我把 Agent 的执行过程当作一条可观测流水线，而不是黑盒 prompt。每个节点都要知道耗时、输出规模、是否 fallback，这样线上回答质量差时能定位是检索、评估、补检索还是生成阶段的问题。”
- **状态**: ✅ 已修复

### Issue 22: Research 任务状态没有持久化当前步骤

- **文件**: `backend/src/api/research.py`, `backend/src/db/models.py`, `backend/src/agent/research_graph.py`, `docs/schema.sql`
- **问题**: `/api/research/{task_id}/status` 的 `current_step` 一直返回 `None/TODO`
- **影响**: 用户和运维无法知道长任务卡在 planner、retriever、analyst、checker 还是 writer
- **修复**: `ResearchTask` 增加 `current_step` 字段；Research Graph 支持 `on_step` async callback；后台任务在节点推进时写回 DB；任务创建状态改为 schema 允许的 `running`
- **状态**: ✅ 已修复

### Issue 23: Agent 节点缺少策略化错误处理

- **文件**: `backend/src/agent/runtime.py`, `backend/src/agent/graph.py`
- **问题**: 节点失败时只有抛异常或节点内部零散 fallback，缺少统一的 timeout、错误等级和 fallback 策略
- **影响**: 可选节点失败可能中断整条链路；关键节点失败又缺少明确的 critical 标记
- **修复**: 新增 `NodePolicy`，支持 `error_level`、`timeout_seconds` 和 `fallback_result`；trace wrapper 根据 policy 决定 fallback 或 fail-fast，并写入 trace
- **为什么做**: Agent 里不同节点的重要性不同。检索失败可能应该中断，来源对比失败可以降级，答案反思失败可能不应该影响主答案。把这些都写在散落的 try/except 里，会让错误策略不可见、不可测试、不可复用。
- **怎么实现**:
  - 新增 `NodePolicy`，字段包括 `error_level`、`timeout_seconds`、`fallback_result`。
  - `AgentRuntime.node_policies` 按节点名保存策略。
  - `run_traced_node()` 执行节点前读取 policy。
  - 如果配置了 `timeout_seconds`，用 `asyncio.wait_for()` 包裹节点。
  - 如果节点异常且 policy 非 critical 且有 fallback，则返回 fallback，并写入 `status=fallback` 的 trace。
  - 如果是 critical 或没有 fallback，则记录 error trace 后继续抛异常。
- **代码位置**:
  - `backend/src/agent/runtime.py`：`NodePolicy`、`AgentRuntime.policy_for()`。
  - `backend/src/agent/graph.py`：`runtime_policy()`、`run_traced_node()` 中的 timeout/fallback/fail-fast 逻辑。
  - `backend/tests/test_agent_orchestration.py`：`test_traced_node_uses_policy_fallback_for_handled_errors`。
- **运行时行为**:
  - 默认策略是 critical，节点失败会 fail-fast。
  - 可选节点可以显式配置 handled fallback，例如 `compare_sources` 失败时返回 `{"source_comparison": None}`。
  - fallback 不会静默吞掉错误，trace 中会记录原始 error、error_level 和 fallback 状态。
- **面试怎么讲**: “我没有把所有异常都 catch 掉，而是按节点策略处理。关键链路 fail-fast，增强节点可降级。这样系统不会因为非核心能力失败而整体不可用，也不会把关键故障悄悄吞掉。”
- **状态**: ✅ 已修复

### Issue 24: LLM 结构化输出缺少 schema 校验

- **文件**: `backend/src/agent/schemas.py`, `backend/src/agent/nodes.py`
- **问题**: 即使能从 LLM 响应中解析出 JSON，也无法保证字段枚举、范围和类型正确
- **影响**: 非法 action、越界 coverage、错误 intent 可能进入 Agent 控制流
- **修复**: 新增 `QueryAnalysis` 和 `RetrievalEvaluation` Pydantic schema；LLM JSON 解析后必须通过 schema 校验，否则进入受控 fallback
- **为什么做**: “能解析成 JSON”不等于“业务上合法”。Agent 的路由字段由 LLM 输出控制，如果模型返回 `action=delete`、`coverage=999` 或 `relevance=PERFECT`，裸 dict 会污染控制流。
- **怎么实现**:
  - 保留原有 `parse_json_object()`，先解决 markdown fence / 前置说明等格式问题。
  - 新增 Pydantic schema：`QueryAnalysis` 和 `RetrievalEvaluation`。
  - `parse_query_analysis()` 和 `parse_retrieval_evaluation()` 在 JSON 解析后执行 `model_validate()`。
  - 校验失败会抛异常，被节点原有 fallback 捕获，进入受控默认策略。
- **代码位置**:
  - `backend/src/agent/schemas.py`：Pydantic schema 定义。
  - `backend/src/agent/nodes.py`：`parse_query_analysis()`、`parse_retrieval_evaluation()`。
  - `backend/tests/test_agent_orchestration.py`：非法 LLM 结构输出回归测试。
- **运行时行为**:
  - Query analysis 只接受 `factual/analysis/comparison/summary` 这类 intent。
  - Retrieval evaluation 只接受 `HIGH/MEDIUM/LOW`、`coverage=0..100`、`action=proceed/re_search/expand`。
  - 非法结构不会进入 `should_research()` 等路由逻辑，而是触发 fallback。
- **面试怎么讲**: “LLM 输出要过两层门：第一层是解析成 JSON，第二层是 schema 校验。尤其是 action 这种控制流字段不能相信模型随便给，否则 Agent 就会被非法结构牵着走。”
- **状态**: ✅ 已修复

### Issue 25: DB schema 改动缺少 migration

- **文件**: `backend/migrations/001_add_research_current_step.sql`
- **问题**: 只改 ORM 和 `schema.sql` 不会自动更新已有数据库
- **影响**: 已部署环境查询/写入 `current_step` 时可能因列不存在失败
- **修复**: 增加幂等 migration SQL：`ALTER TABLE research_tasks ADD COLUMN IF NOT EXISTS current_step VARCHAR(32)`
- **为什么做**: ORM 和 `schema.sql` 只描述“新环境应该长什么样”，不会自动修改已经存在的生产数据库。之前给 `ResearchTask` 增加 `current_step` 后，如果线上表没有这个列，后台任务写进度会直接失败。
- **怎么实现**:
  - 新增 `backend/migrations/001_add_research_current_step.sql`。
  - 使用 `ADD COLUMN IF NOT EXISTS` 保证幂等。
  - 保持 ORM、`docs/schema.sql` 和 migration 三者一致。
  - 增加测试检查 migration 文件存在且包含幂等加列语句。
- **代码位置**:
  - `backend/migrations/001_add_research_current_step.sql`：真实迁移 SQL。
  - `backend/src/db/models.py`：`ResearchTask.current_step` ORM 字段。
  - `docs/schema.sql`：全量建表 schema。
  - `backend/tests/test_schema_migrations.py`：migration 回归测试。
- **运行时行为**:
  - 新环境可以通过 `schema.sql` 创建带 `current_step` 的表。
  - 旧环境执行 migration 后补齐 `current_step` 列。
  - migration 可重复执行，不会因为列已存在而失败。
- **面试怎么讲**: “改 ORM 不是数据库迁移。生产库已经有表和数据，必须用 migration 把旧 schema 演进到新 schema。我用了幂等 SQL，确保多环境、多次执行都安全。”
- **状态**: ✅ 已修复

### Issue 26: Agent trace 缺少成本和规模指标

- **文件**: `backend/src/agent/runtime.py`, `backend/src/agent/graph.py`
- **问题**: 只有节点耗时还不够，无法判断某个节点是不是输出过大、检索为空、答案过长、unsupported claims 过多，后续也不方便接真实 token/cost。
- **影响**: 线上成本和质量问题难以归因。例如一次回答变慢，可能是检索结果太多、上下文太长、生成答案过长或反思发现太多未支撑断言。
- **修复**: `AgentRuntime.trace_metrics()` 为节点输出生成基础 metrics，包括 `approx_output_tokens`、`retrieval_results_count`、`filtered_results_count`、`sources_count`、`answer_chars`、`unsupported_claims_count`。
- **为什么做**: Agent 成本不只来自最终生成，也来自中间节点的上下文规模和工具调用规模。先建立统一 metrics 结构，后续才能把 provider usage、真实 token 和费用接进来。
- **怎么实现**:
  - 在 `AgentRuntime.trace_metrics()` 中根据节点 output 提取指标。
  - 用 `len(str(output)) // 4` 估算 `approx_output_tokens`，作为没有 provider usage 时的粗粒度代理指标。
  - 对常见列表输出记录 count，避免 trace 里塞完整内容。
  - 对答案和答案反思记录 `answer_chars`、`unsupported_claims_count`。
  - `run_traced_node()` 把 metrics 写入每条 `node_traces`。
- **代码位置**:
  - `backend/src/agent/runtime.py`：`trace_metrics()`、`_approx_tokens()`。
  - `backend/src/agent/graph.py`：trace event 中写入 `metrics`。
  - `backend/tests/test_agent_orchestration.py`：验证 retrieve trace 包含 `retrieval_results_count` 和 `approx_output_tokens`。
- **运行时行为**:
  - 每个节点 trace 都会带 `metrics`。
  - retrieve 节点可以看到检索结果数量。
  - generation/reflection 节点可以看到答案长度和未支撑 claim 数。
  - 当前 token 是近似值，后续可替换或补充真实 LLM usage。
- **面试怎么讲**: “我先不假装已经有完整计费系统，而是先把成本观测的接口打出来。trace 里有输出规模、结果数量、答案长度和近似 token，后续接真实 provider usage 时只需要丰富 metrics，不需要重做观测模型。”
- **状态**: ✅ 已修复

### Issue 27: 答案缺少 claim-level citation binding

- **文件**: `backend/src/agent/nodes.py`, `backend/src/agent/graph.py`, `backend/src/api/models.py`, `backend/src/api/routes.py`
- **问题**: 之前只返回 sources 列表，无法知道答案中每个具体 claim 由哪些来源支撑。
- **影响**: 用户无法逐句核查答案；自动评估也只能粗略判断“有无来源”，无法判断 claim 和 source 的绑定关系。
- **修复**: 增加 deterministic citation binding：将答案切分为 claims，为每个 claim 匹配最相关 source indexes，输出 `support_level` 和 `support_score`；非流式响应和流式 done 事件都返回 `citations`。
- **为什么做**: 新闻 RAG 的核心不是“列出来源”，而是“每个结论都能追溯到来源”。claim-level citation 是后续 hover citation、自动评估和 groundedness 升级的基础。
- **怎么实现**:
  - `split_answer_claims()` 将答案切成 claim-sized sentences。
  - `tokenize_for_support()` 提取中英文 token。
  - `score_claim_support()` 计算 claim 和单个 source 的 token overlap。
  - `bind_claim_citations()` 为每个 claim 选择 strongest supporting sources，并输出 `supported/partial/unsupported`。
  - `self_reflect()` 返回 `citations`，并基于 citation support 生成 `unsupported_claims`。
- **代码位置**:
  - `backend/src/agent/nodes.py`：claim 切分、source 匹配、citation binding。
  - `backend/src/agent/graph.py`：流式完成后执行 `self_reflect` 并在 done 事件返回 citations。
  - `backend/src/api/models.py`：`Citation` / `QueryResponse.citations`。
  - `backend/src/api/routes.py`：非流式响应携带 citations。
  - `backend/tests/test_agent_orchestration.py`：claim-to-source binding 回归测试。
- **运行时行为**:
  - 每条 citation 包含 `claim`、`source_indexes`、`support_level`、`support_score`。
  - source index 使用 1-based 编号，对齐返回 sources 的展示顺序。
  - 无支撑 claim 会返回空 `source_indexes` 且 `support_level=unsupported`。
- **面试怎么讲**: “我把 citation 从文档级提升到 claim 级。不是简单把 sources 附在答案后面，而是让每个具体判断都绑定到来源。这样既能提高用户信任，也能为后续自动评估和 NLI groundedness 打基础。”
- **状态**: ✅ 已修复
