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
