# RAG News Intelligence 面试说明

## 项目定位

RAG News Intelligence 是一个面向中英文资讯研究的 RAG 系统，目标是把分散新闻源、Hacker News 和全文网页内容沉淀成可检索证据库，再通过多阶段 Agent 自动完成问题规划、证据检索、分析归纳、可信度校验和报告生成。

系统适合回答“某个行业/技术/公司近期发生了什么、有哪些趋势和风险、哪些结论有来源支撑”这类研究型问题，而不是只做单轮聊天。

## 核心链路

1. 数据采集：接入 8+ 个中英文 RSS 源、Hacker News Firebase API，并使用 trafilatura 抓取网页全文。
2. 文本处理：按文章标题、时间、来源、导语和正文切分 chunk，生成稳定 content_hash 去重。
3. Embedding 入库：调用火山引擎 Embedding API，按 batch 写入 Milvus。
4. 混合检索：语义召回、关键词召回、标题匹配并行执行，RRF 融合后做时间/来源加权，再通过 CrossEncoder 可选重排。
5. Agent 工作流：Planner → Retriever → Analyst → Checker → Writer，支持缺口补检、最大工具调用次数和分步重试边界。
6. 过程追踪：保存 evidence_trace、execution_log、quality_report、memory_snapshot，支持恢复和复盘。
7. 交付：前端通过 SSE 展示进度、实时日志、Markdown 报告、PPT 大纲预览和质量评估结果。

## 如何实现

### 资讯采集与全文解析

RSS 采集器维护中英文新闻源配置，覆盖 TechCrunch、The Verge、Ars Technica、BBC、Reuters、36氪、少数派、钛媒体、爱范儿、澎湃新闻等。每条 RSS entry 会标准化成 title、content、source、language、category、published_at、url、content_hash。

Hacker News 采集器通过 Firebase API 拉取 top/new/best stories。HN 原始 item 经常只有标题和外链，所以系统在外链存在时调用 trafilatura 抽取全文，失败时回退到 HN 元信息。

关键文件：

- `backend/src/ingestion/rss_collector.py`
- `backend/src/ingestion/hn_collector.py`
- `backend/src/ingestion/indexer.py`

### Embedding 与 Milvus Collection

入库前先通过 `chunk_article()` 切分文章。每个 chunk 保留固定头部，避免检索结果脱离上下文。Embedding 使用火山引擎 API，Milvus schema 包含 embedding、title、content、source、language、category、published_at、content_hash、url、chunk_id、parent_doc_id、user_id、company_id 等字段。

Milvus 建 IVF_FLAT 向量索引，metric 使用 COSINE；title/content 建标量索引供关键词/标题路径过滤。写入前按 content_hash 查询去重，避免 RSS 重复发布导致 collection 膨胀。

关键文件：

- `backend/src/vectorstore/milvus_store.py`
- `backend/src/vectorstore/embedding.py`
- `backend/src/ingestion/chunker.py`

### 混合检索方案

检索分三路：

- 语义召回：对 query 做 embedding，在 Milvus 中按 COSINE 搜索。
- 关键词召回：对 title/content 做 LIKE 查询，覆盖专有名词、公司名、事件名。
- 标题匹配：单独查 title，提升精确新闻标题或实体标题命中。

三路结果用 RRF 融合，权重为 semantic=0.5、keyword=0.3、title=0.2，k=60。融合后再做时间衰减和来源质量 boost。最后接 CrossEncoderReranker，如果本地安装了 sentence-transformers，就加载 `BAAI/bge-reranker-v2-m3`；没有模型时使用轻量 lexical fallback，不阻断主流程。

关键文件：

- `backend/src/retrieval/retriever.py`
- `backend/src/retrieval/fusion.py`
- `backend/src/retrieval/boost.py`
- `backend/src/retrieval/reranker.py`

### 检索评估

评估脚本内置 20 条查询，覆盖 Sports、Sci/Tech、Business、World 四类，每类 5 条。指标包括 Precision、Recall、NDCG @ K=1/3/5/10，目标是 MultiPath Precision@5 >= 0.8。

评估结果输出到 `backend/data/eval_results/{timestamp}.json`，用于对比纯语义检索与多路检索。

关键文件：

- `backend/scripts/evaluate_retrieval.py`
- `backend/tests/test_evaluate_retrieval.py`

### 多阶段 Agent 工作流

LangGraph 工作流包含 5 个阶段：

- Planner：识别研究目标、受众、时间范围，并拆成 3-5 个子问题。
- Retriever：对每个子问题调用混合检索，合并去重证据。
- Analyst：基于证据归纳趋势、机会、风险。
- Checker：检查证据覆盖率、可信度问题、冲突和缺口。
- Writer：输出 Markdown 报告、PPT outline 和逐页 slides。

Checker 如果发现可行动缺口，会回到 Retriever 做补检；配置类缺口和 API key 缺口不会无限循环。`max_tool_calls` 控制最大工具调用次数，避免 Agent 失控。

关键文件：

- `backend/src/agent/research_graph.py`
- `backend/src/agent/research_tools.py`
- `backend/src/agent/research_state.py`

### 任务记忆与证据追踪

系统把研究过程拆成四层保存：

- evidence_trace：每条证据的编号、标题、来源、URL、发布时间、分数和摘要。
- execution_log：每个阶段的执行状态和工具调用次数。
- quality_report：证据覆盖率、来源多样性、90 天时效性、可信度问题、缺口。
- memory_snapshot：把 query、plan、analysis、gaps、conflicts、evidence_trace 合成一次可恢复快照。

这些字段写入 `research_tasks`，方便前端恢复任务，也方便回答“Agent 为什么得出这个结论”。

关键文件：

- `backend/src/agent/research_memory.py`
- `backend/src/api/research.py`
- `backend/migrations/002_add_research_memory_quality.sql`

### 长期目标推进

长期目标不是每次只丢一个 query 给 LLM，而是在每次执行时组装历史 plan、已有 evidence、缺口列表、当前 step 和质量报告。下一轮可以围绕 gaps 做补检，也可以基于 memory_snapshot 继续扩展同一研究目标。

这个设计让 Agent 的研究状态可恢复、可增量推进：上一次已经确认的证据不用重复找，缺口会成为下一轮任务输入。

### 前端交付链路

前端新增 Deep Research 面板：

- 创建研究任务：`POST /api/research`
- SSE 订阅进度：`GET /api/research/{task_id}/events?token=...`
- 实时展示 current_step、execution_log、quality_report
- 展示 Markdown 报告和 PPT 大纲预览

关键文件：

- `frontend/src/components/ResearchPanel.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/types/index.ts`
- `frontend/src/styles.css`

## 业务难点

### 1. 新闻数据源质量不稳定

RSS 摘要经常很短，HN 只有标题和外链，中文站点页面结构差异大。解决方式是 RSS 摘要和 trafilatura 全文双通道，全文失败时保留摘要或元信息，不让采集链路因为单篇失败中断。

### 2. 单一路径检索容易漏召回

纯向量检索对实体名、标题、短新闻不稳定；纯关键词检索又不理解语义。系统用 semantic + keyword + title 三路召回，再用 RRF 融合，既保留语义泛化，也保留标题和实体精确命中。

### 3. Agent 容易循环或编造

研究任务天然开放，Agent 可能不断补检。这里通过 `max_tool_calls`、配置类缺口过滤、Checker 缺口判断和 evidence_trace 约束，让补检有边界，让报告必须围绕已有证据生成。

### 4. “为什么得出这个结论”必须可解释

只保存最终答案无法复盘。系统额外保存 evidence_trace、execution_log、quality_report、memory_snapshot，使每个结论能回到来源、得分、阶段状态和缺口。

### 5. 面向交付不只是回答问题

业务方需要的是报告、PPT 大纲、质量评估和可追踪过程。因此前端不只显示聊天答案，还提供 SSE 进度、实时日志、Markdown 报告、PPT outline 和质量面板。

## 可以在面试中强调的结果

- 独立搭建了从 RSS/HN/trafilatura 到 Embedding/Milvus 的资讯数据流水线。
- 设计了多路召回 + RRF + boost + CrossEncoder re-ranker 的混合检索架构。
- 建立 Precision@5、Recall、NDCG 的离线评估脚本，目标 Precision@5 >= 0.8。
- 用 LangGraph 实现多阶段 Deep Research Agent，支持缺口补检和最大工具调用限制。
- 引入证据追踪和任务记忆，使研究过程可恢复、可追溯、可复盘。
- 前端通过 SSE 实时展示研究过程，并交付 Markdown 报告和 PPT 大纲。

## 验证记录

- `DEBUG=false uv run pytest tests/test_research_graph_orchestration.py tests/test_evaluate_retrieval.py`：10 passed。
- `npm run build`：通过。
