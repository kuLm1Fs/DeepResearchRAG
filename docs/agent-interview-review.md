# Agent 工程化收敛面试复盘

本文整理本项目 Agent 功能收敛中发现的问题、排查方式、解决方案和后续开发注意点。面试时可以把它讲成一次从 demo 级 RAG Agent 向生产级 Agent 编排收敛的工程复盘。

## 背景

项目是一个新闻 RAG 系统，后端使用 FastAPI + LangGraph，支持普通问答 Agent 和 Deep Research Agent。目标不是简单让 Agent “能回答”，而是让它在生产环境下具备一致的编排语义、可测试性、可观测性、错误可控和答案可信度。

这轮收敛重点处理了以下几类问题：

- 流式和非流式路径行为不一致
- LangGraph 节点顺序错误
- Agent state 字段语义混乱
- LLM JSON 输出解析脆弱
- Deep Research 编排存在明显 bug
- async API 环境中混用 `asyncio.run()`
- 节点内部硬编码外部依赖，难以测试
- 答案缺少证据支撑校验

## 1. 流式和非流式 Agent 编排不一致

### 问题

普通 RAG Agent 有两个入口：

- 非流式：走 LangGraph compiled graph
- 流式：手写调用 `analyze_query -> plan_retrieval -> retrieve -> generate_answer_stream`

流式路径缺少：

- `evaluate_relevance`
- `re_search`
- `compare_sources`
- `self_reflect`

这意味着同一个 query，在 `stream=true` 和 `stream=false` 下可能使用不同材料、不同补检索策略、不同质量控制。

### 如何排查

排查时重点看 API 入口：

- `/api/query` 中 `request.stream=true` 调用 `run_agent_stream`
- `request.stream=false` 调用 `run_agent`

然后比较两个函数内部节点顺序。发现非流式走 LangGraph，而流式手写节点，并且节点集合不一致。

### 如何解决

抽出共享的 pre-generation 编排流程：

```python
analyze_query
-> plan_retrieval
-> retrieve
-> evaluate_relevance
-> optional re_search
-> compare_sources
```

流式和非流式都在生成答案前走同样的业务语义。流式只是在最后一步用 `stream_chat()` 逐 token 输出。

### 后续开发注意点

- 一个 Agent 可以有多个输出形态，但不应该有多套业务语义。
- 新增 streaming、batch、CLI、API 入口时，要确认它们共享同一套 orchestration。
- 面试里可以强调：这不是代码复用问题，而是生产一致性问题。

## 2. `compare_sources` 节点顺序错误

### 问题

Graph 中 `compare_sources` 原来在 `retrieve` 之前执行：

```text
analyze_query -> compare_sources -> plan_retrieval -> retrieve
```

但 `compare_sources` 依赖 `retrieval_results`。检索前没有结果，所以这个节点实际永远没有有效输入。

### 如何排查

查看 LangGraph DAG 的边定义，并结合每个 node 读取的 state 字段：

- `compare_sources` 读取 `state["retrieval_results"]`
- `retrieval_results` 由 `retrieve` 写入

读写顺序反了。

### 如何解决

改为：

```text
retrieve -> evaluate_relevance -> optional re_search -> compare_sources -> generate_answer
```

这样多源对比基于最终检索材料，而不是空 state。

### 后续开发注意点

- Agent 节点不只要看函数名，还要看 state read/write contract。
- 编排图中的“看起来有节点”不代表功能真的生效。
- 后续加节点前，应明确输入字段、输出字段和前置依赖。

## 3. `reflection` 字段语义混乱

### 问题

同一个 `reflection` 字段同时表示：

- 检索质量评估结果：`relevance`、`coverage`、`action`
- 答案质量反思结果：`quality`、`issues`、`needs_revision`

这会导致后一个节点覆盖前一个节点的结果。尤其是补检索路由依赖 `reflection.action`，如果字段被覆盖，控制流就会变得不可靠。

### 如何排查

看 state schema 和节点返回值：

- `evaluate_relevance()` 返回 `{"reflection": ...}`
- `self_reflect()` 也返回 `{"reflection": ...}`

两个节点的业务含义完全不同，但写同一个字段。

### 如何解决

拆成两个字段：

```python
retrieval_evaluation
answer_reflection
```

并短期保留 `reflection` 作为兼容别名，避免一下子破坏旧调用方。

### 后续开发注意点

- Agent state 是跨节点协议，不是随手塞数据的 dict。
- 字段命名要体现业务语义，避免“万能字段”。
- 面试里可以说：状态设计是 Agent 工程化的核心之一。

## 4. LLM JSON 输出解析过于脆弱

### 问题

多个节点直接使用：

```python
json.loads(response.strip())
```

但真实 LLM 常常返回：

```text
```json
{ ... }
```
```

或者带一句说明：

```text
Here is the JSON:
{ ... }
```

这会导致结构化输出解析失败，进入 fallback。

### 如何排查

看 prompt 里虽然要求 “Output ONLY valid JSON”，但代码不能假设模型百分百遵守。单测中模拟 fenced JSON，就能复现失败。

### 如何解决

新增统一 JSON object 提取函数：

- 去掉 markdown fence
- 从文本中扫描第一个可解析 JSON object
- 解析失败才 fallback

普通 RAG Agent 和 Deep Research tools 复用同一套解析逻辑。

### 后续开发注意点

- LLM 是不稳定上游，不能把 prompt 当作强约束。
- 结构化输出必须有 parser、schema 校验和 fallback。
- 后续可以进一步引入 Pydantic schema validation。

## 5. Deep Research Planner 子问题没有进入 Retriever

### 问题

Planner 会返回 `sub_questions`，但 graph state 没有更新该字段。Retriever 最终退回使用原始 query。

这导致“研究计划”看似生成了，实际没有驱动后续检索。

### 如何排查

沿 state 流转排查：

- `_call_planner()` 返回 plan
- graph node 只写入 `plan`
- `_call_retriever()` 从 `state["sub_questions"]` 读取
- `sub_questions` 从未写入 state

### 如何解决

新增 planner node：

```python
plan = await _call_planner(state)
sub_questions = plan.get("sub_questions") or plan.get("research_questions") or []
return {
    "plan": plan,
    "sub_questions": sub_questions,
}
```

### 后续开发注意点

- 多 Agent / multi-tool 编排中，每一步输出必须明确进入下一步输入。
- 不能只看单个工具函数是否正确，要看工具之间的数据契约是否闭合。

## 6. Deep Research Checker 被重复调用

### 问题

Checker 节点原来写法类似：

```python
{
    "check_result": _call_checker(state),
    "gaps": _call_checker(state).get("gaps", [])
}
```

这会调用两次 LLM。

### 如何排查

看 graph node lambda，发现 `_call_checker(state)` 出现两次。加一个 fake checker 计数测试即可证明。

### 如何解决

拆成明确函数：

```python
check_result = await _call_checker(state)
return {
    "check_result": check_result,
    "gaps": check_result.get("gaps", []),
    "conflicts": check_result.get("conflicts", []),
}
```

### 后续开发注意点

- LLM 调用是昂贵且非确定性的，不能在一个节点里无意调用两次。
- 对外部工具调用要有计数、成本和幂等性意识。

## 7. Deep Research 补检索会重复拉同一批材料

### 问题

Checker 发现 gaps 后回到 Retriever，但 Retriever 仍可能使用原始子问题，并且新 evidence 会覆盖旧 evidence。

结果是：

- 补检索没有围绕 gaps 进行
- 第一轮证据可能丢失
- tool call 被浪费

### 如何排查

看 conditional edge：

```text
checker -> retriever
```

再看 retriever node 如何选择 queries。发现它没有区分首轮检索和 gap-driven 补检索。

### 如何解决

补检索时优先使用 `state["gaps"]` 作为查询，并把新旧 evidence 合并去重。

### 后续开发注意点

- 补检索不是“再跑一遍检索”，而是根据缺口定向检索。
- Evidence 应该累积，而不是覆盖。
- 后续可以记录 evidence provenance：来自第几轮、哪个 gap、哪个 query。

## 8. `asyncio.run()` 出现在 async API 链路中

### 问题

Deep Research tools 中有同步包装：

```python
def planner(...):
    return asyncio.run(_async_llm_planner(...))
```

FastAPI 本身已经运行在 event loop 中。如果 API 请求里调用 `await run_research()`，内部再调用 `asyncio.run()`，会报：

```text
RuntimeError: asyncio.run() cannot be called from a running event loop
```

### 如何排查

搜索：

```bash
rg "asyncio.run" backend/src/agent
```

再看调用链：

```text
FastAPI async endpoint
-> await run_research()
-> LangGraph node
-> planner()
-> asyncio.run(...)
```

没配置 LLM key 时可能走 stub，不会暴露。一旦生产配置真实 LLM key，就会进入真实 async 调用路径。

### 如何解决

新增 async-first API：

```python
aplanner
aanalyst
achecker
awriter
```

Research Graph 节点改成 async node：

```python
async def _planner_node(state):
    plan = await _call_planner(state)
```

同步包装保留给 CLI 或普通脚本兼容，但 FastAPI / LangGraph async 链路不再使用它们。

### 后续开发注意点

- 在 async Web 服务中，业务链路应保持 async all the way down。
- `asyncio.run()` 只适合程序入口或没有 event loop 的脚本。
- 面试里这点很有价值：它体现了对 FastAPI 运行模型和生产事故触发条件的理解。

## 9. 节点内部硬编码 LLM / Retriever / Milvus

### 问题

普通 RAG Agent 节点内部直接创建：

```python
create_llm(...)
MilvusStore()
MultiPathRetriever(...)
```

问题是：

- 单测容易打到真实外部服务
- 不方便做 provider fallback
- 不方便做 timeout、retry、熔断、灰度
- 不方便统计 token / cost / latency

### 如何排查

写一个 runtime 注入测试，期望节点使用 fake LLM / fake Retriever。测试会失败并尝试连接真实 Milvus，说明依赖边界没有抽出来。

### 如何解决

新增 `AgentRuntime`：

```python
runtime.create_llm()
runtime.create_retriever()
runtime.with_answer_cache(llm)
```

节点从 `state["runtime"]` 获取 runtime；没有注入时使用默认 runtime。

### 后续开发注意点

- Agent 节点应该依赖抽象能力，而不是直接创建基础设施对象。
- Runtime 后续可以继续承载 timeout policy、fallback policy、trace recorder。
- Deep Research 目前还可以继续接入统一 runtime。

## 10. 答案缺少 groundedness 校验

### 问题

原来的 `self_reflect` 只做启发式检查：

- 答案长度
- 来源数量
- 标题关键词是否出现在答案里

这不能判断答案中的具体 claim 是否被 sources 支撑。

### 如何排查

构造一个答案：

```text
OpenAI released a new enterprise agent platform. Revenue doubled this quarter.
```

source 只支持前一句，不支持 revenue doubled。原逻辑无法标出第二句是 unsupported claim。

### 如何解决

增加轻量 groundedness 检查：

- 把答案切分成 claim-sized sentences
- 对答案 claim 和 sources 做 token overlap
- 支撑不足的句子写入：

```python
answer_reflection.unsupported_claims
```

### 后续开发注意点

- 词面检查只是第一步，适合 MVP 和低成本兜底。
- 生产级可以升级为：
  - claim extraction
  - evidence retrieval per claim
  - LLM/NLI entailment
  - unsupported / contradicted / low-confidence 分类
- 最终目标是让 Agent 明确区分“有证据支持”和“基于推断”。

## 11. Issue 记录和测试闭环

### 问题

Agent 系统的问题如果只靠口头记忆，很容易后续重复踩坑。

### 如何排查

看项目已有 issue 文档，发现可以延续 `docs/issue.md` 的格式记录。

### 如何解决

把本轮发现的问题写入 `docs/issue.md`，并标注：

- 已修复
- 部分修复
- 后续待改进

同时补测试覆盖：

- JSON fenced block 解析
- 流式路径是否执行补检索和多源对比
- Planner 子问题是否进入 state
- Checker 是否只调用一次
- 补检索是否基于 gaps
- runtime 注入是否生效
- unsupported claim 是否被识别

### 后续开发注意点

- 每次 Agent 编排改动都要有 workflow-level test。
- 单元测试只证明函数对，workflow test 才能证明编排对。
- 面试里可以强调：Agent 工程化不是只写 prompt，而是测试、状态、编排和观测一起做。

## 面试表达框架

可以按这个顺序讲：

1. **先讲背景**：这是一个 FastAPI + LangGraph 的新闻 RAG Agent，目标从 demo 收敛到生产可用。
2. **再讲发现问题的方法**：我不是直接改 prompt，而是沿 API 入口、Graph 节点、State 字段、外部依赖、测试路径排查。
3. **讲几个典型问题**：
   - stream / non-stream 编排不一致
   - `asyncio.run()` 嵌套 event loop 风险
   - LLM JSON 解析不稳定
   - Checker 重复调用 LLM
   - 答案缺少证据支撑校验
4. **讲解决方案**：
   - 共享 pre-generation orchestration
   - async-first research graph
   - runtime dependency injection
   - state schema 拆分
   - groundedness check
5. **最后讲经验**：
   - Agent 生产化的关键不是“更复杂的 prompt”，而是稳定的编排、清晰的状态、可控的依赖、可观测的执行和可验证的答案。

## 后续可以继续收敛的方向

- Deep Research 全面接入 `AgentRuntime`
- 每个 LangGraph node 增加 timeout / retry / fallback policy
- 每个节点输出 structured trace：耗时、输入摘要、输出摘要、错误等级、fallback 标记、token/cost（已完成基础 `node_traces`，后续可补 token/cost）
- Research task 的 `current_step` 写回数据库，支持 `/research/{task_id}/status` 实时展示（已完成基础状态回写）
- groundedness 从词面匹配升级到 LLM/NLI entailment
- source comparison 从来源数量升级为事实冲突检测
- 将 state schema 升级为更严格的 Pydantic model 或 TypedDict + validator
