# RAG News Intelligence — Issues

## 发现的问题

### Issue 1: agent/nodes.py 相对导入路径错误
- **文件**: `backend/src/agent/nodes.py`
- **问题**: `from ..templates import load_prompt` 用了双点 `..`，但 `templates.py` 在同一个 `agent/` 包内，应该用单点 `.`
- **影响**: `from agent.nodes import ...` 会报 `ImportError: attempted relative import beyond top-level package`
- **修复**: 
  - `from ..templates import load_prompt` → `from .templates import load_prompt`
  - `from ..llm import create_llm` → `from llm import create_llm`（llm 是 src 的子包，不是 agent 的父级）
  - `from ..llm.cache import CachedLLM` → `from llm.cache import CachedLLM`
- **状态**: ✅ 已修复

### Issue 2: llm/cache.py 循环导入
- **文件**: `backend/src/llm/cache.py`
- **问题**: 文件内容是 `from .cache import CachedLLM`，即从自身导入，形成循环
- **影响**: 导入 `llm.cache` 会失败或行为异常
- **修复**: 需要将 CachedLLM 类定义放在正确的位置，或将 self-import 改为实际实现
- **状态**: ⏳ 待修复

### Issue 3: api/models.py 缺少 fastapi 依赖
- **文件**: `backend/src/api/models.py`
- **问题**: venv 中未安装 fastapi，导致导入失败
- **影响**: API 模型无法导入
- **修复**: `pip install fastapi` 已执行
- **状态**: ✅ 已修复

### Issue 4: ingestion/base.py 缺少 Article dataclass
- **文件**: `backend/src/ingestion/base.py`
- **问题**: 采集器代码中引用 Article 类但 base.py 中未定义，实际使用 dict 代替
- **影响**: 代码可运行但类型不一致
- **状态**: ⏳ 待确认是否需要添加

### Issue 5: core/logging.py Processor 类型错误
- **文件**: `backend/src/core/logging.py`
- **问题**: `Processor(googlers=redact_sensitive)` 把类型别名当类实例化
- **修复**: CC 改为 `redact_sensitive`（直接传函数），删除 Processor 导入
- **状态**: ✅ 已修复

### Issue 6: core/logging.py structlog.INFO 不存在
- **文件**: `backend/src/core/logging.py`
- **问题**: `getattr(structlog, settings.log_level.upper(), structlog.INFO)` 中 structlog 没有 INFO 属性
- **修复**: CC 改为 `getattr(logging, settings.log_level.upper(), logging.INFO)`
- **状态**: ✅ 已修复

### Issue 7: scripts/seed_data.py 和 evaluate_retrieval.py 未验证
- **状态**: ✅ 已验证通过

---

## 测试汇总

| 模块 | 状态 | 备注 |
|------|------|------|
| core.config | ✅ | |
| core.logging | ✅ | |
| core.errors | ✅ | |
| core.middleware | ✅ | |
| core.cache | ✅ | |
| ingestion.base | ✅ | dict 模式，无 Article |
| ingestion.rss | ✅ | |
| ingestion.hn | ✅ | |
| ingestion.dataset | ✅ | |
| ingestion.pipeline | ✅ | |
| retrieval.retriever | ✅ | |
| retrieval.fusion | ✅ | |
| llm.client | ✅ | |
| llm.cache | ❌ | 循环导入 |
| vectorstore.embedding | ✅ | |
| vectorstore.milvus | ✅ | |
| agent.state | ✅ | |
| agent.nodes | ❌→✅ | 相对导入已修复 |
| agent.templates | ✅ | |
| cli.main | ✅ | |
| api.models | ❌→✅ | fastapi 已安装 |

### Issue 8: Embedding batch_size=50 导致零向量
- **文件**: `backend/src/vectorstore/embedding.py`
- **问题**: `BATCH_SIZE = 50` 超过 aihubmix API 限制（max 16 items），所有向量为零
- **影响**: Milvus 余弦相似度全部返回 0.0，搜索永远找不到结果
- **修复**: `BATCH_SIZE = 50 → 16`
- **状态**: ✅ 已修复

### Issue 9: Semantic search async 嵌套 asyncio.run() 报错
- **文件**: `backend/src/retrieval/retriever.py`
- **问题**: `embed_texts()` 内部调用 `asyncio.run()`，在 FastAPI async 上下文中运行报错
- **影响**: `semantic_search_failed: error='asyncio.run() cannot be called from a running event loop'`
- **修复**: 使用 `embed_texts_async()` 替代
- **状态**: ✅ 已修复

### Issue 10: 前端 markdown 渲染缺失
- **文件**: `frontend/src/components/ChatWindow.tsx`
- **问题**: LLM 返回 markdown 格式但前端用纯文本渲染，格式混乱
- **修复**: 添加 `react-markdown` + `remark-gfm`
- **状态**: ✅ 已修复

### Issue 11: .env.prod 被 git 追踪
- **文件**: `backend/.env.prod`
- **问题**: 含 API key 占位的配置文件不应提交到 git
- **修复**: git rm --cached + .gitignore 添加 **/.env*
- **状态**: ✅ 已修复

### Issue 12: Agent workflow 过于简单
- **文件**: `backend/src/agent/nodes.py`, `backend/src/agent/graph.py`
- **问题**: 原流程只有分词→检索→LLM回答，无意图分析、query改写、质量评估
- **修复**: 升级为 LLM 驱动的 agent workflow（6个节点 + 补检索循环）
- **状态**: ✅ 已修复
