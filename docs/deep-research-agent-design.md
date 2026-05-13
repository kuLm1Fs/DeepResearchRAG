# RAG News Intelligence — 深度研搜 Agent 接入方案

## 1. 项目定位

当前项目已经具备 RAG 基础能力：数据采集、向量化、Milvus 检索、多路召回、LangGraph Agent 问答和来源展示。下一阶段的目标不是只增强问答能力，而是把项目升级为一个面向垂直领域的智能分析系统。

目标形态：

```text
RAG 证据引擎 + Deep Research Agent 分析层 + 报告/PPT 交付层
```

对于 AI 行业现状分析这类任务，系统应该能够：

- 根据用户问题拆解研究任务；
- 从垂直 RAG 知识库中检索证据；
- 对多来源信息做归纳、对比和校验；
- 识别信息缺口并补充检索；
- 输出带来源的分析报告、PPT 大纲或逐页 PPT 内容。

## 2. 总体架构

```text
用户问题
  ↓
Research Orchestrator 主智能体
  ↓
研究规划与任务拆解
  ↓
调用多个专业子智能体
  ↓
子智能体通过 RAG 工具检索证据
  ↓
分析、交叉验证、反思补充
  ↓
生成分析报告 / PPT 大纲 / PPT 内容
```

当前项目中的 RAG 能力作为“证据层”存在，负责找到可信资料；Deep Research Agent 作为“分析层”存在，负责规划、分工、判断和组织交付物。

## 3. Agent 编排设计

采用主从式多 Agent 架构，而不是让多个 Agent 自由聊天。主从式架构更容易控制任务边界、调试执行链路，并减少多 Agent 发散。

### 3.1 主智能体

主智能体命名为：

```text
Research Orchestrator
```

职责：

- 理解用户目标；
- 判断研究范围、受众和输出形式；
- 拆解研究任务；
- 调度子智能体；
- 汇总子任务结果；
- 判断是否需要补充检索；
- 组织最终报告或 PPT 内容。

主智能体不直接查询 Milvus，也不直接处理大量原始资料。它通过子智能体和工具获取结构化结果。

### 3.2 子智能体

第一版建议保留 5 个核心子智能体：

| 子智能体 | 职责 |
|---|---|
| Planner Agent | 将用户问题拆解成研究计划和子问题 |
| Retriever Agent | 调用当前 RAG 检索能力，返回资料和来源 |
| Analyst Agent | 从资料中提炼趋势、机会、风险和判断 |
| Evidence Checker Agent | 检查来源可信度、信息冲突、引用覆盖度和缺口 |
| Writer Agent | 生成最终报告、PPT 大纲或逐页内容 |

针对 AI 行业分析，后续可以进一步扩展领域型子智能体：

| 子智能体 | 研究方向 |
|---|---|
| Model Trend Agent | 大模型发布、能力变化、模型生态 |
| Market Agent | 投融资、商业化、企业落地 |
| Policy Agent | 政策监管、备案、合规风险 |
| Infra Agent | 算力、芯片、云服务、能源约束 |
| China Market Agent | 中国市场、国产模型、应用场景 |

第一版不建议拆太多领域 Agent，应优先跑通稳定流程。

## 4. 多 Agent 通信协议

多 Agent 之间不采用自由对话，而采用结构化通信。所有子智能体必须返回统一 JSON，便于调试、缓存、评估和二次生成。

### 4.1 子智能体输出格式

```json
{
  "task_id": "market_trend",
  "claim": "AI Agent 正在从演示型工具走向企业工作流入口",
  "evidence": [
    {
      "title": "source title",
      "url": "https://example.com",
      "source": "OpenAI Blog",
      "published_at": 1710000000,
      "quote_or_summary": "核心证据摘要",
      "confidence": 0.86
    }
  ],
  "insights": [
    "企业关注点从模型能力转向流程集成",
    "主要瓶颈是权限、安全、成本和可靠性"
  ],
  "risks": [
    "样本来源偏向英文科技媒体",
    "缺少企业内部落地数据"
  ],
  "missing_info": [
    "需要补充中国市场案例"
  ]
}
```

### 4.2 通信规则

```text
主 Agent -> 子 Agent：任务说明 + 输出格式 + 可用工具
子 Agent -> 主 Agent：结构化发现 + 证据 + 缺口
主 Agent -> Retriever：补充检索请求
Checker -> 主 Agent：冲突、低可信、缺证据提醒
Writer -> 主 Agent：最终交付物草稿
```

主智能体只接收可汇总结果，不接收未经整理的大段资料。大量原文、检索结果和中间笔记应写入任务文件或后端存储，由路径或引用 ID 关联。

## 5. 任务划分流程

以用户输入为例：

```text
分析 AI Agent 行业现状，并生成一份给产品经理看的报告。
```

推荐执行流程如下。

### 5.1 意图解析

识别用户请求中的关键参数：

- 主题：AI Agent 行业；
- 受众：产品经理；
- 输出：分析报告；
- 时间窗口：默认最近 3-6 个月；
- 地域：默认全球 + 中国；
- 重点：产品机会、落地趋势、风险和竞争格局。

### 5.2 研究规划

Planner Agent 生成研究子问题：

- 最近有哪些重要产品和模型发布？
- 企业落地到了什么阶段？
- 头部玩家有哪些？
- 开源生态有哪些变化？
- 商业化和投融资趋势如何？
- 主要风险和瓶颈是什么？
- 对产品经理有什么机会？

### 5.3 证据检索

Retriever Agent 针对每个子问题调用 RAG 工具，优先检索：

- 官方博客和 release note；
- 新闻源；
- 研究报告；
- GitHub / Hugging Face；
- 政策、备案和监管信息；
- 财报、投资者关系资料和行业报告。

### 5.4 分析提炼

Analyst Agent 将证据转化为结构化判断：

- 行业现状；
- 关键趋势；
- 代表公司和产品；
- 机会；
- 风险；
- 不确定性。

### 5.5 证据校验

Evidence Checker Agent 检查：

- 每个核心判断是否至少有 1-2 个来源支撑；
- 是否优先使用一手来源；
- 来源是否过旧；
- 是否存在互相冲突的信息；
- 是否缺少中文市场、政策或企业落地数据；
- 是否出现没有证据支撑的推断。

### 5.6 补充检索

如果 Evidence Checker 发现缺口，Research Orchestrator 会生成补充检索任务，重新调用 Retriever Agent。

### 5.7 交付物生成

Writer Agent 根据已验证的研究结果生成：

- Markdown 分析报告；
- PPT 大纲；
- 逐页 PPT 内容 JSON；
- 后续可扩展为 `.pptx` 文件。

## 6. RAG 接入方式

当前项目的 RAG 能力不应直接写进 Agent 内部，而应封装成工具。

推荐工具接口：

```python
rag_search(query: str, filters: dict, top_k: int) -> list[Evidence]
```

返回结构：

```json
[
  {
    "title": "文章标题",
    "content": "正文或摘要",
    "source": "OpenAI Blog",
    "url": "https://example.com",
    "category": "model_release",
    "source_type": "official_blog",
    "published_at": 1710000000,
    "score": 0.82
  }
]
```

这样可以保持 RAG 与 Agent 解耦：

- RAG 负责找证据；
- Agent 负责规划和分析；
- 检索质量可以单独评估；
- 后续可以替换搜索源或向量库；
- Agent 不应绕过证据直接编造结论。

## 7. 垂直领域数据隔离

如果项目转向 AI 行业分析，建议新建垂直 collection，而不是直接混用原始通用新闻库。

推荐 collection：

```text
ai_industry_articles
```

每条数据建议包含：

```text
domain
dataset_id
source
source_type
category
url
language
published_at
content_hash
credibility_score
```

推荐分类体系：

| category | 含义 |
|---|---|
| model_release | 模型发布 |
| research | 论文和研究 |
| product | 产品更新 |
| funding | 投融资 |
| enterprise_adoption | 企业落地 |
| policy | 政策监管 |
| infra | 芯片、算力、云和能源 |
| open_source | 开源生态 |
| safety | 安全、伦理和风险 |
| china_market | 中国市场 |

推荐来源类型：

| source_type | 说明 |
|---|---|
| official_blog | 官方博客、公告、release note |
| research_report | 研究报告 |
| paper | 论文 |
| reputable_news | 可信媒体 |
| community | 社区讨论 |
| financial | 财报、投融资、IR 资料 |
| policy | 政策、监管、备案 |

## 8. 记忆管理设计

系统中需要区分四类记忆，避免把缓存、用户偏好和知识库混在一起。

### 8.1 工作记忆

保存一次研究任务运行中的状态。

内容：

- 用户问题；
- 研究计划；
- 子任务状态；
- 检索结果；
- 中间结论；
- 缺口列表；
- 最终草稿。

生命周期：一次研究任务。

实现方式：LangGraph / DeepAgents state。

### 8.2 证据记忆

保存可长期复用的垂直领域资料。

内容：

- 新闻文章；
- 论文；
- 研究报告；
- 官网更新；
- 政策信息；
- 财报和公告；
- 社区讨论。

生命周期：长期。

实现方式：Milvus collection，例如 `ai_industry_articles`。

### 8.3 任务记忆

保存每次深度研究的过程和产物。

内容：

```text
research_plan.json
retrieval_results.json
analysis_notes.md
evidence_matrix.json
final_report.md
slides_outline.json
```

生命周期：跨会话，可复用。

实现方式：DeepAgents Backend、文件系统或数据库。

### 8.4 用户记忆

保存用户偏好和长期上下文。

内容：

- 用户角色；
- 默认语言；
- 报告风格；
- 默认时间窗口；
- 默认输出格式；
- 偏好的分析角度；
- PPT 默认页数。

示例：

```json
{
  "user_id": "u_001",
  "role": "product_manager",
  "language": "zh",
  "style": "conclusion_first",
  "default_time_window": "last_3_months",
  "preferred_output": "markdown_report",
  "ppt_pages": 10
}
```

生命周期：跨会话。

实现方式：StoreBackend 或数据库，必须按 `user_id` 隔离。

## 9. 交付物结构

第一版建议优先生成 Markdown 报告，稳定后再生成 PPT。

### 9.1 分析报告结构

```text
Executive Summary
行业现状
关键趋势
代表公司/产品
机会分析
风险分析
对目标用户的建议
引用来源
```

### 9.2 PPT 内容结构

PPT 生成前先输出结构化 JSON：

```json
{
  "title": "AI Agent 行业现状分析",
  "audience": "产品经理",
  "slides": [
    {
      "page": 1,
      "title": "核心结论",
      "bullets": [
        "AI Agent 正在从演示工具走向企业工作流入口",
        "落地瓶颈集中在权限、安全、可靠性和成本"
      ],
      "speaker_notes": "本页用于开场，先给出判断，再展开证据。",
      "sources": ["source_id_1", "source_id_2"]
    }
  ]
}
```

## 10. 分阶段实施计划

### 第一阶段：RAG 工具化

目标：将当前 `MultiPathRetriever` 封装为 `rag_search` 工具。

交付：

- RAG 工具接口；
- 统一 Evidence 返回结构；
- 支持 domain、category、source_type、time range 等过滤；
- 基础检索测试集。

### 第二阶段：固定研究工作流

目标：先用 LangGraph 实现稳定流程。

流程：

```text
Intent Parser -> Planner -> Retriever -> Analyst -> Checker -> Writer
```

交付：

- 一条可运行的深度研究链路；
- Markdown 报告输出；
- 来源引用和缺口提示。

### 第三阶段：DeepAgents 接入

目标：将固定工作流和 RAG 工具接入 DeepAgents 主智能体。

交付：

- Research Orchestrator；
- Retriever 子智能体；
- Analyst 子智能体；
- Checker 子智能体；
- Writer 子智能体。

### 第四阶段：记忆落地

目标：保存研究任务过程、产物和用户偏好。

交付：

- 任务文件存储；
- 用户偏好存储；
- 历史报告复用；
- 按 `user_id` 和 `task_id` 隔离。

### 第五阶段：PPT 化

目标：将报告转换为 PPT 大纲和逐页内容。

交付：

- `slides_outline.json`；
- 前端 PPT 预览；
- 后续扩展 `.pptx` 导出。

## 11. 第一版成功标准

第一版不以“Agent 看起来很聪明”为目标，而以“分析结果可信、可追溯、可复用”为目标。

核心标准：

- 每个核心结论都有来源；
- 每个来源可以追溯到 URL 或原文；
- 每份报告有清晰结构；
- 发现缺证据时会补充检索；
- 不同用户画像会改变输出角度；
- 输出结果可以复用为报告或 PPT；
- 检索层、分析层和交付层边界清晰。

## 12. 推荐落地顺序

推荐先做：

```text
AI 行业现状分析 Markdown 报告
```

而不是一开始直接做完整 PPT 文件。

原因：

- 报告比 PPT 更容易验证内容质量；
- 可以优先打磨证据、引用和分析逻辑；
- 报告结构稳定后，PPT 只是二次表达；
- 便于评估 Agent 是否真的基于 RAG 证据生成结论。

当 Markdown 报告质量稳定后，再将其转换为：

```text
报告 -> PPT 大纲 -> 逐页 PPT JSON -> PPT 文件
```

