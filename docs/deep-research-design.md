# Deep Research Agent — 设计文档

## 1. 项目定位

### 1.1 目标

在现有 RAG News Intelligence 基础上，扩展 Deep Research Agent 能力，将系统从"问答引擎"升级为"垂直领域智能分析系统"。

目标形态：

```
RAG 证据引擎 + Deep Research Agent 分析层 + 报告/PPT 交付层
```

### 1.2 核心能力

- 根据用户问题拆解研究任务
- 从垂直知识库中检索多源证据
- 对证据做归纳、对比、校验
- 识别信息缺口并补充检索
- 输出带来源的分析报告、PPT 大纲、逐页 PPT 内容

### 1.3 与现有 RAG 的关系

```
现有 RAG → 问答引擎
  - 单次检索
  - 简单问答
  - 流式输出

Deep Research → 深度研究
  - 多轮研究流程
  - 结构化报告
  - 来源可追溯
```

现有 RAG 能力作为"证据层"存在，Deep Research Agent 作为"分析层"和"交付层"。

---

## 2. 总体架构

```
用户问题
  ↓
Research Orchestrator (Supervisor Agent)
  ↓
调用 5 个 Tool Function
  ↓
子 Tool 通过 RAG 检索证据
  ↓
分析、校验、反思
  ↓
生成报告 / PPT 大纲 / PPT 内容
  ↓
存储任务记忆 + 用户偏好更新
```

---

## 3. Agent 架构：Supervisor + Multi-Tool

### 3.1 设计决策

**不是多 Agent，而是 Supervisor + Multi-Tool**：

| 方案 | 描述 | 适用场景 |
|------|------|---------|
| 多 Agent | 每个子模块有自己 LLM，可自主决策 | 开放性任务 |
| **Multi-Tool** | Supervisor（1个 LLM）+ 5个 Tool Function | **流程固定，需要精确控制** |

**选择 Multi-Tool 的原因**：

- 流程固定（规划→检索→分析→检查→写报告），不需要子模块自主决策
- Supervisor 作为中央调度器更可控
- 调试简单，出问题好排查
- 5 个 Tool 只是函数调用，没有独立 LLM

### 3.2 架构图

```
┌──────────────────────────────────────────────────────────────┐
│  Research Orchestrator (Supervisor Agent)                   │
│  - 1 个 LLM（DeepSeek/Qwen/OpenAI）                       │
│  - 决策调用哪个 Tool                                       │
│  - 决策传什么参数                                         │
│  - 判断是否需要补充检索                                     │
└──────────────────────────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┬──────────────┐
          │              │              │              │
          ▼              ▼              ▼              ▼
    ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐
    │ planner   │ │ retriever │ │ analyst   │ │ checker   │ ...
    │ Tool      │ │ Tool      │ │ Tool      │ │ Tool      │
    └───────────┘ └───────────┘ └───────────┘ └───────────┘

所有 Tool 都是函数，不是独立 Agent
```

### 3.3 Tool 定义

```python
# 每个 Tool 有明确定义，Supervisor 按需调用
tools = [
    {
        "name": "planner",
        "description": "分析用户问题，生成研究计划",
        "parameters": {
            "query": str,           # 用户问题
            "user_profile": dict     # 用户偏好
        }
    },
    {
        "name": "retriever",
        "description": "从知识库检索证据",
        "parameters": {
            "sub_questions": list[str],  # 拆解后的子问题
            "filters": dict              # 过滤条件
        }
    },
    {
        "name": "analyst",
        "description": "从证据中提炼趋势、机会、风险",
        "parameters": {
            "evidence": list[dict],  # 证据列表
            "focus": str             # 分析重点
        }
    },
    {
        "name": "checker",
        "description": "检查来源可信度、冲突、缺口",
        "parameters": {
            "claims": list[dict],   # 结论列表
            "evidence": list[dict]  # 证据列表
        }
    },
    {
        "name": "writer",
        "description": "生成报告和 PPT 内容",
        "parameters": {
            "analysis": dict,        # 分析结果
            "check_result": dict,   # 检查结果
            "output_format": str    # markdown / ppt_json / both
        }
    }
]
```

---

## 4. 子 Tool 详细设计

### 4.1 Planner Tool

**职责**：意图分析 → 受众识别 → 研究计划 → 子问题拆解

**输入**：用户原始问题 + 用户偏好

**输出**：

```json
{
  "task_id": "research_001",
  "intent": "行业分析",
  "audience": "产品经理",
  "time_window": "最近3个月",
  "language": "zh",
  "research_questions": [
    "AI Agent 产品发布动态",
    "企业落地案例",
    "投融资趋势"
  ],
  "analysis_angles": ["产品机会", "落地瓶颈", "竞争格局"],
  "priority": ["投融资", "产品发布"]
}
```

**Prompt 模板**：

```
你是一个专业的研究规划师。分析用户问题，生成研究计划。

用户问题: {query}
用户偏好: {user_profile}

请输出 JSON 格式：
{
  "intent": "分析/对比/概览",
  "audience": "受众",
  "time_window": "时间范围",
  "language": "语言",
  "research_questions": ["子问题1", "子问题2"],
  "analysis_angles": ["分析角度1", "分析角度2"],
  "priority": ["优先级排序"]
}
```

---

### 4.2 Retriever Tool

**职责**：调用 MultiPathRetriever → 多轮检索 → 结果合并去重

**输入**：子问题列表 + 过滤条件

**输出**：

```json
{
  "task_id": "research_001",
  "evidence": [
    {
      "id": "art_001",
      "title": "OpenAI 发布 GPT-5",
      "content": "正文摘要...",
      "source": "OpenAI Blog",
      "source_type": "official_blog",
      "category": "model_release",
      "url": "https://...",
      "published_at": 1710000000,
      "relevance_score": 0.92
    }
  ],
  "total_count": 15,
  "diversity_score": 0.85,
  "recency_rate": 0.73
}
```

**实现**：

```python
async def retriever(sub_questions: list[str], filters: dict) -> dict:
    all_results = []
    seen_ids = set()

    for q in sub_questions:
        results = await multi_path_retriever.retrieve(q, top_k=5)
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                all_results.append(r)

    # 按相关度排序
    all_results.sort(key=lambda x: x["relevance_score"], reverse=True)
    return {"evidence": all_results[:15]}
```

---

### 4.3 Analyst Tool

**职责**：证据 → 趋势分析 + 机会分析 + 风险分析 → 结构化输出

**输入**：证据列表 + 分析重点

**输出**：

```json
{
  "task_id": "research_001",
  "trends": [
    {
      "claim": "AI Agent 正在从演示工具走向企业工作流",
      "evidence_ids": ["art_001", "art_003"],
      "confidence": 0.88
    }
  ],
  "opportunities": [
    {
      "claim": "企业级 AI Agent 平台存在巨大市场空间",
      "evidence_ids": ["art_005"],
      "confidence": 0.82
    }
  ],
  "risks": [
    {
      "claim": "安全性和权限管理是主要瓶颈",
      "evidence_ids": ["art_007"],
      "confidence": 0.85
    }
  ],
  "representative_companies": [
    {"name": "OpenAI", "focus": "企业级 Agent 平台"},
    {"name": "Microsoft", "focus": "Copilot 生态"}
  ]
}
```

---

### 4.4 Checker Tool

**职责**：来源可信度 / 时效 / 缺口检测 + 冲突检测（低优先级）

**输入**：结论列表 + 证据列表

**输出**：

```json
{
  "task_id": "research_001",
  "source_quality": {
    "high_credibility": 8,    # 官方博客、研究报告
    "medium_credibility": 5, # 新闻媒体
    "low_credibility": 2     # 社区讨论
  },
  "recency_check": {
    "outdated_sources": ["art_010"],  # 超过 3 个月
    "recent_rate": 0.73
  },
  "gaps": [
    {"type": "missing_market", "description": "缺少中国市场数据"},
    {"type": "missing_financial", "description": "缺少企业落地收入数据"}
  ],
  "conflicts": [
    {
      "claim_a": "OpenAI 领先",
      "claim_b": "Anthropic 领先",
      "confidence": "low"  # 低优先级
    }
  ],
  "missing_info": [
    "需要补充：中国AI Agent 市场报告"
  ]
}
```

**冲突检测**：加入但作为低优先级，不阻塞流程，Writer 输出中标注"存在潜在冲突"。

---

### 4.5 Writer Tool

**职责**：Markdown 报告 + PPT 大纲 JSON + 逐页内容 JSON

**输入**：分析结果 + 检查结果 + 输出格式

**输出**：

```json
{
  "task_id": "research_001",
  "markdown_report": "# AI Agent 行业现状分析\n\n## 执行摘要\n...",
  "slides_outline": {
    "title": "AI Agent 行业现状分析",
    "audience": "产品经理",
    "slides": [
      {
        "page": 1,
        "title": "核心结论",
        "bullets": ["AI Agent 正在从演示工具走向企业工作流"],
        "speaker_notes": "先给结论，再展开",
        "sources": ["art_001"]
      }
    ]
  },
  "page_content": {
    "title": "AI Agent 行业现状分析",
    "slides": [
      {
        "page": 1,
        "title": "核心结论",
        "content": {
          "title_slide": "AI Agent 行业现状分析",
          "subtitle": "给产品经理的行业洞察"
        },
        "bullets": [...],
        "speaker_notes": "...",
        "sources": ["art_001", "art_002"]
      }
    ]
  }
}
```

---

## 5. LLM 路由设计

### 5.1 Supervisor Prompt

```
你是 Research Orchestrator，负责协调深度研究流程。

你有 5 个工具可用：
- planner: 分析问题，生成研究计划
- retriever: 检索证据
- analyst: 分析证据，提取洞察
- checker: 检查证据质量和完整性
- writer: 生成最终报告

工作流程：
1. 先用 planner 分析用户问题
2. 根据 planner 输出决定需要哪些子问题
3. 用 retriever 检索证据
4. 用 analyst 分析证据
5. 用 checker 验证
6. 如果 checker 发现重大缺口，返回 retriever 补充检索
7. 最后用 writer 生成报告

规则：
- 每个结论必须有证据支撑
- 识别并报告信息缺口
- 检测不同来源间的潜在冲突（低优先级）
- 报告必须结构清晰，包含来源引用
```

### 5.2 路由示例

```
用户: "分析 AI Agent 行业现状，生成给产品经理看的报告"
```

```
Step 1: supervisor → planner({"query": "...", "user_profile": {...}})
Step 2: supervisor → retriever({"sub_questions": ["AI Agent 产品发布", "企业落地"]})
Step 3: supervisor → analyst({"evidence": [...], "focus": "all"})
Step 4: supervisor → checker({"claims": [...], "evidence": [...]})
         checker 返回: {"gaps": ["缺少中国市场"], "conflicts": [...]}
         ↓ 缺口大
Step 5: supervisor → retriever({"sub_questions": ["中国AI Agent 市场"]})
Step 6: supervisor → writer({"analysis": {...}, "check_result": {...}, "output_format": "both"})
```

---

## 6. 记忆管理

### 6.1 四层架构

```
┌─────────────────────────────────────────┐
│  用户层记忆 (User Memory)                │
│  - 用户偏好、历史行为、报告风格           │
│  - PostgreSQL user_preferences 表      │
│  - 生命周期: 永久                       │
└─────────────────────────────────────────┘
                      ↓ 读取
┌─────────────────────────────────────────┐
│  任务层记忆 (Task Memory)               │
│  - 研究计划、检索结果、分析笔记、最终报告  │
│  - PostgreSQL research_tasks 表        │
│  - 生命周期: 任务级，可恢复历史            │
└─────────────────────────────────────────┘
                      ↓ 检索
┌─────────────────────────────────────────┐
│  证据层记忆 (Evidence Memory)            │
│  - 所有已采集的文章、论文、报告          │
│  - Milvus ai_industry_articles         │
│  - 生命周期: 长期，持续积累               │
└─────────────────────────────────────────┘
                      ↓ 查询
┌─────────────────────────────────────────┐
│  工作层记忆 (Working Memory)             │
│  - 当前研究的中间状态、子问题、缺口列表   │
│  - LangGraph State（内存）              │
│  - 生命周期: 单次研究，执行完释放         │
└─────────────────────────────────────────┘
```

### 6.2 Working Memory 结构

```python
class WorkingMemory(TypedDict):
    query: str                      # 用户原始问题
    task_id: str                   # 任务 ID
    user_id: str                   # 用户标识
    current_step: str               # 当前步骤: planner/retriever/...
    tool_call_count: int           # Tool 调用次数
    plan: dict                      # Planner 输出
    sub_questions: list[str]        # 拆解后的子问题
    evidence: list[dict]            # Retriever 返回的证据
    analysis: dict                # Analyst 输出
    check_result: dict             # Checker 输出
    gaps: list[str]                 # 识别的缺口
    conflicts: list[dict]          # 检测到的冲突
    final_output: dict              # Writer 输出
    failed_step: str | None        # 失败步骤
    retry_count: int               # 重试次数
```

### 6.3 用户偏好收集

**方式 1：显式收集（前端设置页面）**

```json
{
  "user_id": "u_001",
  "language": "zh",
  "report_style": "conclusion_first",
  "default_time_window": "last_3_months",
  "preferred_output": "markdown_report",
  "ppt_pages": 10
}
```

**方式 2：隐式收集（从行为推断）**

| 行为 | 推断偏好 |
|------|---------|
| 每次都导出 .md | `preferred_output = "markdown"` |
| 经常看 PPT 预览 | `preferred_output = "ppt_json"` |
| 总是查最近 1 个月 | `default_time_window = "last_1_month"` |
| 英文问题居多 | `language = "en"` |

### 6.4 偏好读取与注入

研究开始时，Planner 自动读取用户偏好：

```python
def get_user_preferences(user_id: str) -> dict:
    prefs = db.query("SELECT * FROM user_preferences WHERE user_id = ?", user_id)
    if not prefs:
        return {"language": "zh", "report_style": "conclusion_first"}
    return prefs


async def planner(query: str, user_id: str) -> dict:
    prefs = get_user_preferences(user_id)

    prompt = f"""
    用户问题: {query}
    用户偏好: 语言={prefs['language']}, 风格={prefs['report_style']}, 时间窗口={prefs['default_time_window']}

    请生成研究计划...
    """
```

---

## 7. 容错机制

### 7.1 错误处理策略

| 场景 | 处理方式 |
|------|---------|
| LLM API 超时 | 指数退避重试（1s → 2s → 4s），最多 3 次 |
| JSON 解析失败 | fallback 降级返回，不阻塞流程 |
| 未知 Tool | 白名单校验，返回错误 |
| Tool 调用超限 | 强制终止（MAX_TOOL_CALLS = 20） |
| 证据不足 | 继续流程，标注"证据可能不足" |

### 7.2 重试机制

```python
@tool("planner")
@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
    reraise=True
)
async def planner(query: str, user_id: str) -> dict:
    llm = create_llm(...)
    response = await llm.chat(messages)
    return parse_json(response)
```

### 7.3 降级处理

```python
try:
    result = json.loads(response)
except json.JSONDecodeError:
    logger.warning("planner_json_parse_failed")
    return {
        "status": "partial",
        "sub_questions": [query],  # fallback: 直接用原始问题
        "error": "parse_failed"
    }
```

### 7.4 分步重试

```python
# 用户可单独重试失败的步骤
POST /api/research/{task_id}/retry?step=retriever

# research_tasks 表记录失败信息
failed_step: "retriever"
retry_count: 1
```

---

## 8. 数据库设计

### 8.1 存储架构

| 数据库 | 用途 | 数据特点 |
|--------|------|---------|
| **PostgreSQL** | 用户、公司、任务、认证 | 关系型，结构化 |
| **Milvus** | 向量检索 | ai_industry_articles collection |
| **MinIO** | 文件存储 | PPT/报告文件 |

### 8.2 ai_industry_articles Collection Schema

```
ai_industry_articles
├── id (INT64, auto_id)
├── embedding (FLOAT_VECTOR, dim=1024)
├── title (VARCHAR, max=512)
├── content (VARCHAR, max=8192)
├── summary (VARCHAR, max=1024)
├── author (VARCHAR, max=128)
├── tags (JSON)
├── source (VARCHAR, max=128)           # 来源媒体
├── source_type (VARCHAR, max=32)       # official_blog / research_report / reputable_news / ...
├── category (VARCHAR, max=32)           # model_release / funding / policy / infra / china_market / ...
├── language (VARCHAR, max=10)           # zh / en
├── published_at (INT64)                # 发布时间戳
├── user_id (VARCHAR, max=64)          # 所属用户（多用户隔离）
├── domain (VARCHAR, max=32)           # 固定 "ai_industry"
└── content_hash (VARCHAR, max=64)    # 去重
```

### 8.3 PostgreSQL 表结构

详见 `docs/schema.sql` 和 `docs/schema.md`，包含：

- companies（公司表，含配额管理）
- users（用户表）
- research_tasks（研究任务表）
- user_preferences（用户偏好表）
- refresh_tokens（刷新令牌表）
- audit_logs（审计日志表）

---

## 9. 认证与用户

### 9.1 JWT 认证流程

```
1. 注册 → users + companies（公司不存在时自动创建）
2. 登录 → 验证密码 → 生成 access_token + refresh_token
3. 请求 → Authorization: Bearer {access_token}
4. token 过期 → 用 refresh_token 换新 access_token
5. 登出 → refresh_token 设置 revoked = true
```

### 9.2 Token 结构

| Token | 用途 | 有效期 | 存储 |
|-------|------|--------|------|
| access_token | 鉴权 | 1-2 小时 | localStorage |
| refresh_token | 刷新 | 7-30 天 | httpOnly Cookie |

### 9.3 数据隔离

所有查询强制加 company_id 条件：

```sql
SELECT * FROM research_tasks
WHERE company_id = :current_company_id
  AND user_id = :current_user_id
```

---

## 10. 报告质量评估

### 10.1 方案 A：自动指标评估（P1）

基于检索指标自动计算：

| 指标 | 计算方式 | 标准 |
|------|---------|------|
| 证据覆盖率 | 有来源支撑的结论数 / 总结论数 | ≥ 80% |
| 来源多样性 | 独立来源数 / 总使用来源数 | ≥ 3 个来源 |
| 证据时效性 | 3 个月内的来源占比 | ≥ 60% |
| 来源可信度 | source_type 加权平均分 | ≥ 0.7 |
| 缺口识别率 | 主动标注的缺口数 | > 0 |

```json
{
  "quality_score": 0.85,
  "metrics": {
    "evidence_coverage": 0.92,
    "source_diversity": 0.78,
    "recency_rate": 0.65,
    "credibility_score": 0.82
  },
  "gaps_found": 3,
  "conflicts_found": 1
}
```

### 10.2 方案 B：LLM 评审（P2）

让另一个 LLM 评审报告质量：

| 维度 | 分数 |
|------|------|
| 结构完整性 | 1-10 |
| 论据充分性 | 1-10 |
| 来源可靠性 | 1-10 |
| 缺口识别 | 1-10 |
| 可读性 | 1-10 |

### 10.3 方案 C：用户反馈（P2）

研究完成后让用户打分：

- 内容准确性
- 来源可信度
- 结构清晰度
- 有用程度

存入 audit_logs 表，用于长期优化。

### 10.4 方案 D：对比基准（P3）

准备标准答案数据集，定期跑自动化对比：

- 报告是否包含所有 expected_sections
- 是否引用了 expected_sources
- 来源是否在 max_days_old 内

---

## 11. Redis 应用

### 11.1 LLM 响应缓存（P2）

替代文件缓存，跨进程共享 + TTL 自动过期：

```python
cache_key = hash(prompt + model)
cached = redis.get(cache_key)
if cached:
    return json.loads(cached)
```

### 11.2 热点研究结果缓存（P3）

相同/相似问题加速返回：

```python
cache_key = f"research:{company_id}:{normalize_query(query)}"
redis.setex(cache_key, ttl=86400, value=json.dumps(result))
```

### 11.3 公司级限流（P3）

Redis 实现配额控制，替代 PostgreSQL 查询：

```python
quota_key = f"quota:{company_id}:{current_month}"
current = redis.incr(quota_key)
if current > quota_limit:
    return {"error": "配额已用完"}
```

### 11.4 分布式锁（P3）

多实例部署时采集任务协调：

```python
if redis.set(lock_key, "1", nx=True, ex=300):
    do_crawl()
    redis.delete(lock_key)
```

---

## 12. API 设计

### 12.1 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/auth/register | 注册 + 自动创建公司 |
| POST | /api/auth/login | 登录 + JWT token |
| POST | /api/auth/refresh | 刷新 token |
| POST | /api/auth/logout | 登出 |

### 12.2 研究接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/research | 创建研究任务 |
| GET | /api/research/{task_id} | 获取任务状态和结果 |
| GET | /api/research/{task_id}/stream | SSE 流式进度 |
| POST | /api/research/{task_id}/retry | 分步重试 |
| GET | /api/research/history | 任务历史列表 |

### 12.3 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/admin/users | 成员列表 |
| POST | /api/admin/users/{id}/disable | 禁用用户 |
| GET | /api/admin/company | 公司信息 + 配额 |
| PUT | /api/admin/company/quota | 修改配额 |

---

## 13. 前端设计

### 13.1 Deep Research 入口

独立于 RAG 问答的入口页面：

```
┌─────────────────────────────────────────────────┐
│  [💬 RAG 问答]   [📊 Deep Research]           │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌─────────────────────────────────────────┐  │
│  │  分析 AI Agent 行业现状，                │  │
│  │  生成给产品经理看的报告                  │  │
│  └─────────────────────────────────────────┘  │
│                                                 │
│  [开始研究]                                    │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 13.2 研究进度展示

实时展示每个步骤的状态：

```
Step 1: Planner     ✅ 完成
Step 2: Retriever   🔄 进行中
Step 3: Analyst     ⏳ 等待
Step 4: Checker     ⏳ 等待
Step 5: Writer      ⏳ 等待

[实时日志]
[16:30:01] 开始分析问题...
[16:30:03] 生成研究计划...
[16:30:05] 开始检索证据...
```

### 13.3 报告预览

Markdown 渲染 + 来源链接可点击 + PPT 大纲 JSON 预览。

---

## 14. 实施步骤

### P0：基础设施

- [ ] 新建 ai_industry_articles Collection
- [ ] PostgreSQL 数据库初始化
- [ ] JWT 认证基础设施

### P1：核心链路

- [ ] 5 个 Tool 实现
- [ ] Supervisor 集成
- [ ] 记忆管理层
- [ ] 容错机制
- [ ] 报告质量评估（方案 A）
- [ ] 认证与用户
- [ ] 前端集成

### P2：稳定增强

- [ ] 用户偏好
- [ ] 任务历史
- [ ] Admin 后台
- [ ] Redis LLM 缓存
- [ ] 报告质量（方案 B + C）

### P3：锦上添花

- [ ] 预设分析环节
- [ ] Prompt 版本化
- [ ] 冲突检测正式实现
- [ ] Redis 热点缓存/限流/分布式锁
- [ ] 对比基准评估（方案 D）
- [ ] 部署

---

## 15. 里程碑

| 里程碑 | 包含项 | 验收标准 |
|--------|--------|---------|
| M1 | P0 | Collection + DB + 认证骨架完成 |
| M2 | P1 子 Tool | 5 个 Tool 全通 + 报告生成 |
| M3 | P1 前端 | 登录 + 研究进度 + 报告预览 |
| M4 | M1 + M2 + M3 | 完整端到端可用（ToB 多用户） |
| M5 | P2 + P3 | 历史记录、PPT、Admin 后台 |

---

## 16. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 架构 | Supervisor + Multi-Tool | 流程固定，Multi-Agent 过度设计 |
| LLM 路由 | 可跳过步骤 + 缺口大时补检 | 自适应流程，不死板 |
| 数据存储 | 文件系统 → PostgreSQL | ToB 需要结构化用户管理 |
| 认证方案 | JWT | ToB 多用户、团队管理、配额控制 |
| PPT 交付 | 生成 JSON，前端渲染 | 避免 pptx 库复杂度 |
| 冲突检测 | 加入但低优先级 | MVP 先跑通，不阻塞流程 |
| Redis | LLM 缓存 P2，其余 P3 | 按需引入 |
| 报告评估 | 方案 A P1，BCD 后续 | 自动指标零成本先上 |
| 降级重试 | 不做 Redis 降级重试 | 研究任务耗时分钟级，不需要立即返回降级结果 |
