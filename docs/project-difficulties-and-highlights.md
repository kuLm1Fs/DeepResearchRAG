# RAG News Intelligence 项目难点与亮点

## 项目简介

RAG News Intelligence 是一个面向中英文资讯研究的新闻 RAG 系统，支持 RSS、Hacker News、网页全文解析、Embedding 入库、Milvus 混合检索和多阶段 Agent 研究报告生成。

系统解决的核心问题是：把分散、更新快、可信度不一的新闻资讯，转化成可检索、可追踪、可复盘的研究证据库，并自动生成带来源依据的 Markdown 报告和 PPT 大纲。

## 项目难点

### 1. 多源资讯采集质量不稳定

RSS 源格式差异大，有些只有摘要，有些发布时间字段不完整；Hacker News 很多内容只有标题和外链；中文站点页面结构也不统一。

解决方式：

- 对 RSS entry 做统一标准化，抽取 title、content、source、language、category、published_at、url。
- 对网页外链使用 trafilatura 抓取全文，失败时回退到 RSS 摘要或 HN 元信息。
- 使用 content_hash 做去重，避免重复入库。
- 单条文章失败只记录日志，不中断整个采集任务。

### 2. 单一检索方式召回不稳定

新闻检索里既有语义问题，也有大量实体名、公司名、标题和事件名。纯向量检索容易漏掉精确实体，纯关键词检索又不能理解语义。

解决方式：

- 语义召回：通过 Embedding + Milvus COSINE 向量搜索理解 query 含义。
- 关键词召回：对 title/content 做关键词匹配，提升实体和事件命中率。
- 标题匹配：单独提高标题精确命中能力。
- RRF 融合：把多路结果按 rank 融合，减少单一路径偏差。
- CrossEncoder Re-ranker：对融合候选结果二次排序，提高前 5 条结果质量。

### 3. Agent 容易失控或循环补检

研究型任务开放度高，如果 Agent 发现信息缺口后无限补检，会导致执行时间不可控，也可能产生无依据结论。

解决方式：

- 将 Agent 拆成 Planner、Retriever、Analyst、Checker、Writer 五个阶段。
- Checker 只对可行动缺口触发补检，配置类缺口不会进入循环。
- 设置最大工具调用次数，防止无限执行。
- 每阶段有明确输入输出，便于调试和复盘。

### 4. 结论需要可追溯

普通 RAG 只返回答案和来源列表，但研究报告更需要解释“为什么得出这个结论”。

解决方式：

- 保存 evidence_trace：记录每条证据的标题、来源、URL、发布时间、分数和摘要。
- 保存 execution_log：记录每个 Agent 阶段的执行状态。
- 保存 quality_report：输出证据覆盖率、来源多样性、时效性、可信度问题和缺口。
- 保存 memory_snapshot：把研究状态、证据、分析、缺口和冲突统一存档。

### 5. 交付形态不只是问答

业务侧通常不只需要一句回答，而是需要研究过程、质量指标、报告和汇报材料。

解决方式：

- 后端提供研究任务 API 和 SSE 进度流。
- 前端展示实时步骤、日志、质量评估、Markdown 报告和 PPT 大纲。
- 支持从单轮问答扩展到长期研究目标推进。

## 项目亮点

### 1. 数据流水线完整

项目实现了从资讯采集到向量入库的完整链路：

RSS/HN → trafilatura 全文解析 → chunk 切分 → 火山引擎 Embedding → Milvus Collection → 去重入库。

这不是只调一个 RAG 框架，而是把数据源、解析、切分、Embedding、索引和存储都串起来了。

### 2. 检索方案更贴近真实新闻场景

新闻查询既有语义问题，也有标题、实体、时间和来源维度。项目没有依赖单一路径，而是设计了 semantic、keyword、title 三路召回，并通过 RRF 和重排提升 Precision@5。

### 3. Agent 工作流工程化

Agent 不是一个黑盒 prompt，而是用 LangGraph 拆成多阶段工作流：

- Planner 负责拆问题。
- Retriever 负责找证据。
- Analyst 负责归纳。
- Checker 负责找缺口和冲突。
- Writer 负责生成报告和 PPT 大纲。

这种设计更容易加限制、加观测、加测试，也更适合生产环境。

### 4. 支持证据追踪和复盘

系统保存证据链、执行日志和质量报告，使研究结论可以追溯到具体来源。面试中可以强调：这个设计解决了 RAG 系统常见的“答案看起来合理，但不知道依据是什么”的问题。

### 5. 支持长期研究目标推进

项目不仅支持单轮 Q&A，还设计了 memory_snapshot 和 gaps 列表。下一次执行时可以基于历史证据和未解决缺口继续推进同一个研究目标。

这让系统从“问答机器人”升级成“持续研究助手”。

### 6. 有评估闭环

项目提供检索评估脚本，使用 Precision、Recall、NDCG @ K=1/3/5/10 衡量检索效果，并以 Precision@5 >= 0.8 作为目标。

这体现了不是只完成 demo，而是有指标驱动的调优闭环。

## 面试表达建议

可以这样概括项目亮点：

> 我做的是一个新闻资讯场景的 Deep Research RAG 系统。难点在于新闻数据源质量不稳定、实体检索和语义检索都很重要、Agent 容易循环失控，并且研究结论必须可追溯。我的方案是先搭建 RSS/HN/trafilatura 到 Milvus 的完整数据流水线，再设计语义、关键词、标题三路召回，用 RRF 融合和 CrossEncoder 重排提升 Precision@5。Agent 层用 LangGraph 拆成规划、检索、分析、校验、报告生成五个阶段，并保存 evidence_trace、execution_log、quality_report 和 memory_snapshot，让整个研究过程可恢复、可追踪、可复盘。

## 技术关键词

- FastAPI
- LangGraph
- LangChain
- Milvus
- 火山引擎 Embedding
- RSS / Hacker News API
- trafilatura
- RRF
- CrossEncoder Re-ranker
- SSE
- Markdown Report
- PPT Outline
- Evidence Trace
- Agent Memory
