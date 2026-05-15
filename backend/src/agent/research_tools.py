"""5个 Tool Function 实现（Stub）"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from ..core import settings, get_logger

logger = get_logger(__name__)


def planner(query: str, user_id: str | None = None) -> dict[str, Any]:
    """
    意图分析 + 受众识别 + 研究计划 + 子问题拆解。

    Args:
        query (str): 用户问题
        user_id (str, optional): 用户 ID（用于读取偏好）

    Returns:
        dict: {
            "task_id": str,
            "status": "success" | "error",
            "data": {
                "goals": list[str],
                "audience": str,
                "output_format": str,
                "time_window": str,
                "sub_questions": list[str],
                "estimated_duration_minutes": int
            },
            "errors": list[str],
            "gaps": list[str]
        }
    """
    # 检查 LLM 配置
    if not settings.deepseek_api_key and not settings.openai_api_key and not settings.qwen_api_key:
        logger.warning("planner: no LLM API key configured, returning stub")
        return _stub_planner(query)

    try:
        return _call_llm_planner(query)
    except Exception as e:
        logger.error("planner LLM call failed", error=str(e))
        return _error_result(str(e))


def _call_llm_planner(query: str) -> dict[str, Any]:
    """调用 LLM 生成研究计划（同步包装）"""
    return asyncio.run(_async_llm_planner(query))


async def _async_llm_planner(query: str) -> dict[str, Any]:
    """调用 LLM 生成研究计划（async）"""
    from ..llm import create_llm

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model
    )
    messages = [
        {
            "role": "system",
            "content": """你是一个专业的研究规划师。用户会提出一个研究问题，你需要：
1. 分析问题意图和目标
2. 识别目标受众
3. 制定研究目标
4. 拆解为 3-5 个子问题
5. 确定输出格式和时间范围

请以 JSON 格式输出研究计划，不要包含其他内容：

{
  "goals": ["目标1", "目标2"],
  "audience": "受众描述",
  "output_format": "markdown/ppt/both",
  "time_window": "last_1_month/last_3_months/last_6_months/all",
  "sub_questions": ["子问题1", "子问题2", "子问题3"],
  "estimated_duration_minutes": 预估分钟数
}"""
        },
        {
            "role": "user",
            "content": f"研究问题：{query}"
        }
    ]

    response = await llm.chat(messages)

    # 解析 JSON
    try:
        # 尝试提取 JSON 代码块
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()

        data = json.loads(json_str)
        return {
            "task_id": str(uuid.uuid4())[:8],
            "status": "success",
            "data": data,
            "errors": [],
            "gaps": []
        }
    except json.JSONDecodeError as e:
        logger.warning("planner JSON parse failed", error=str(e), response=response[:200])
        # Fallback: 返回一个基础计划
        return _stub_planner(query)


def _stub_planner(query: str) -> dict[str, Any]:
    """无 LLM 时的 Stub 返回"""
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "success",
        "data": {
            "goals": [f"分析 {query} 相关趋势", "识别机会与风险"],
            "audience": "AI 行业从业者",
            "output_format": "both",
            "time_window": "last_3_months",
            "sub_questions": [query, f"{query} 市场分析", f"{query} 技术进展"],
            "estimated_duration_minutes": 5
        },
        "errors": [],
        "gaps": ["需要配置 LLM API key 以获得真实分析"]
    }


def _error_result(error: str) -> dict[str, Any]:
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "error",
        "data": None,
        "errors": [error],
        "gaps": ["planner 调用失败"]
    }


def retriever(sub_questions: list[str], top_k: int = 5, user_id: str | None = None) -> dict[str, Any]:
    """
    多路检索 + 结果合并去重。

    Args:
        sub_questions (list[str]): 子问题列表
        top_k (int): 每个子问题返回数量
        user_id (str, optional): 用户 ID（用于数据隔离）

    Returns:
        dict: {
            "task_id": str,
            "status": "success" | "error",
            "data": {
                "evidence": list[dict],  # [{title, content, source, url, score, published_at}]
                "total_count": int,
                "sources": list[str]
            },
            "errors": list[str],
            "gaps": list[str]
        }
    """
    task_id = str(uuid.uuid4())[:8]
    all_evidence = []
    errors = []
    gaps = []

    if not settings.volcengine_api_key:
        return {
            "task_id": task_id,
            "status": "error",
            "data": None,
            "errors": ["volcengine API key 未配置"],
            "gaps": ["请配置 VOLCENGINE_API_KEY 以启用检索功能"]
        }

    try:
        from ..vectorstore.embedding import get_embedding_sync
        from ..vectorstore.milvus_store import MilvusStore

        store = MilvusStore()

        for q in sub_questions:
            emb = get_embedding_sync(q)
            if emb is None:
                errors.append(f"子问题 embedding 失败: {q}")
                continue

            try:
                # user_id 过滤暂时禁用（需在 Milvus 建索引后启用）
                # expr = f'user_id == "{user_id}"' if user_id else None
                results = store.search(
                    query_embedding=emb,
                    top_k=top_k,
                    expr=None,  # 暂时禁用，user_id 数据隔离由 PostgreSQL 层处理
                )

                for r in results:
                    all_evidence.append({
                        "title": r.get("title", ""),
                        "content": r.get("content", ""),
                        "source": r.get("source", ""),
                        "url": r.get("url", ""),
                        "score": float(r.get("score", 0.0)),
                        "published_at": r.get("published_at", ""),
                    })
            except Exception as e:
                errors.append(f"检索失败 [{q}]: {e}")

        # 去重（按 content 前 200 字符）
        seen = set()
        deduped = []
        for e in all_evidence:
            key = e["content"][:200] if e["content"] else ""
            if key and key not in seen:
                seen.add(key)
                deduped.append(e)

        sources = list(set(e["source"] for e in deduped if e["source"]))

        if not deduped:
            gaps.append("证据库为空，建议先执行 RSS 采集导入数据")

        return {
            "task_id": task_id,
            "status": "success",
            "data": {
                "evidence": deduped,
                "total_count": len(deduped),
                "sources": sources
            },
            "errors": errors,
            "gaps": gaps
        }

    except Exception as e:
        logger.error("retriever failed", error=str(e))
        return {
            "task_id": task_id,
            "status": "error",
            "data": None,
            "errors": [str(e)],
            "gaps": ["检索过程中发生错误"]
        }


def analyst(evidence: list[dict], focus: str = "all") -> dict[str, Any]:
    """
    趋势分析 + 机会分析 + 风险分析。

    Args:
        evidence (list[dict]): Retriever 返回的证据列表
        focus (str): 分析重点（all/trends/opportunities/risks）

    Returns:
        dict: {
            "task_id": str,
            "status": "success" | "error",
            "data": {
                "trends": list[dict],      # [{topic, description, confidence}]
                "opportunities": list[dict],  # [{title, description, evidence_count}]
                "risks": list[dict],       # [{title, description, severity}]
                "summary": str
            },
            "errors": list[str],
            "gaps": list[str]
        }
    """
    task_id = str(uuid.uuid4())[:8]

    if not evidence:
        return {
            "task_id": task_id,
            "status": "success",
            "data": {
                "trends": [],
                "opportunities": [],
                "risks": [],
                "summary": "证据为空，无法生成分析"
            },
            "errors": [],
            "gaps": ["需要先通过 retriever 获取证据数据"]
        }

    if not settings.deepseek_api_key and not settings.openai_api_key and not settings.qwen_api_key:
        return _stub_analyst(focus)

    try:
        return _call_analyst(evidence, focus)
    except Exception as e:
        logger.error("analyst LLM call failed", error=str(e))
        return _error_analyst(str(e))


def _call_analyst(evidence: list[dict], focus: str) -> dict[str, Any]:
    return asyncio.run(_async_analyst(evidence, focus))


async def _async_analyst(evidence: list[dict], focus: str) -> dict[str, Any]:
    """调用 LLM 分析证据（async）"""
    from ..llm import create_llm

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model
    )

    evidence_snippets = []
    for i, e in enumerate(evidence[:10]):
        snippet = f"[{i+1}] {e.get('title', '')}: {e.get('content', '')[:300]}..."
        evidence_snippets.append(snippet)
    evidence_text = "\n".join(evidence_snippets)

    focus_instruction = {
        "all": "趋势、机会和风险",
        "trends": "趋势",
        "opportunities": "机会",
        "risks": "风险",
    }.get(focus, "趋势、机会和风险")

    messages = [
        {
            "role": "system",
            "content": f"""你是一个专业的行业分析师。根据以下证据材料，进行{focus_instruction}分析。

请以 JSON 格式输出，不要包含其他内容：

{{
  "trends": [{{"topic": "趋势主题", "description": "趋势描述（200字内）", "confidence": 0.85}}],
  "opportunities": [{{"title": "机会标题", "description": "机会描述（200字内）", "evidence_count": 3}}],
  "risks": [{{"title": "风险标题", "description": "风险描述（200字内）", "severity": "high/medium/low"}}],
  "summary": "整体总结（300字内）"
}}"""
        },
        {
            "role": "user",
            "content": f"证据材料：\n{evidence_text}\n\n请进行{focus_instruction}分析。"
        }
    ]

    response = await llm.chat(messages)

    try:
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()
        data = json.loads(json_str)
        return {
            "task_id": str(uuid.uuid4())[:8],
            "status": "success",
            "data": data,
            "errors": [],
            "gaps": []
        }
    except json.JSONDecodeError:
        logger.warning("analyst JSON parse failed, using stub")
        return _stub_analyst(focus)


def _stub_analyst(focus: str) -> dict[str, Any]:
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "success",
        "data": {
            "trends": [{"topic": "趋势待分析", "description": "需要配置 LLM API key 获取真实分析", "confidence": 0.5}],
            "opportunities": [],
            "risks": [],
            "summary": "analyst 处于 stub 模式，需要配置 LLM API key"
        },
        "errors": [],
        "gaps": ["需要配置 LLM API key 以获得真实分析"]
    }


def _error_analyst(error: str) -> dict[str, Any]:
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "error",
        "data": None,
        "errors": [error],
        "gaps": ["analyst 调用失败"]
    }


def checker(claims: list[dict], evidence: list[dict]) -> dict[str, Any]:
    """
    来源可信度 / 时效 / 缺口检测 + 冲突检测。

    Args:
        claims (list[dict]): 待检查的声明
        evidence (list[dict]): 支持证据

    Returns:
        dict: {
            "task_id": str,
            "status": "success" | "error",
            "data": {
                "coverage": float,         # 证据覆盖率 0-1
                "credibility_issues": list[dict],  # [{source, issue}]
                "conflicts": list[dict],   # [{claim_a, claim_b, resolution}]
                "gaps": list[str],         # 缺口列表
                "recommendations": list[str]
            },
            "errors": list[str],
            "gaps": list[str]
        }
    """
    task_id = str(uuid.uuid4())[:8]

    # 空 evidence → 返回 stub（不调用 LLM）
    if not evidence:
        return {
            "task_id": task_id,
            "status": "success",
            "data": {
                "coverage": 0.0,
                "credibility_issues": [],
                "conflicts": [],
                "gaps": ["证据为空，无法进行核查"],
                "recommendations": ["请先通过 retriever 获取证据数据"]
            },
            "errors": [],
            "gaps": ["证据为空"]
        }

    # 无 LLM key → 返回 stub
    if not settings.deepseek_api_key and not settings.openai_api_key and not settings.qwen_api_key:
        return _stub_checker(claims, evidence)

    try:
        return _call_checker(claims, evidence)
    except Exception as e:
        logger.error("checker LLM call failed", error=str(e))
        return _error_checker(str(e))


def _call_checker(claims: list[dict], evidence: list[dict]) -> dict[str, Any]:
    """调用 LLM 进行事实核查（同步包装）"""
    return asyncio.run(_async_checker(claims, evidence))


async def _async_checker(claims: list[dict], evidence: list[dict]) -> dict[str, Any]:
    """调用 LLM 进行事实核查（async）"""
    from ..llm import create_llm

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model
    )

    # 构建 claims 文本（最多 10 条）
    claims_snippets = []
    for i, c in enumerate(claims[:10]):
        claim_text = c.get("claim", c.get("title", c.get("text", str(c))))
        claims_snippets.append(f"[{i+1}] {claim_text}")
    claims_text = "\n".join(claims_snippets)

    # 构建 evidence 文本（最多 10 条，每条 title + content 300字）
    evidence_snippets = []
    for i, e in enumerate(evidence[:10]):
        snippet = f"[{i+1}] {e.get('title', '')}: {e.get('content', '')[:300]}..."
        evidence_snippets.append(snippet)
    evidence_text = "\n".join(evidence_snippets)

    messages = [
        {
            "role": "system",
            "content": """你是一个专业的事实核查员。根据提供的证据材料对待检查的声明进行核查。

请以 JSON 格式输出，不要包含其他内容：

{
  "coverage": 0.0-1.0,  // 证据覆盖率
  "credibility_issues": [{"source": "来源", "issue": "问题描述"}],
  "conflicts": [{"claim_a": "声明A", "claim_b": "声明B", "resolution": "冲突解决说明"}],
  "gaps": ["缺口描述"],
  "recommendations": ["建议描述"]
}"""
        },
        {
            "role": "user",
            "content": f"待检查的声明：\n{claims_text}\n\n支持证据：\n{evidence_text}\n\n请进行事实核查。"
        }
    ]

    response = await llm.chat(messages)

    try:
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()
        data = json.loads(json_str)
        return {
            "task_id": str(uuid.uuid4())[:8],
            "status": "success",
            "data": data,
            "errors": [],
            "gaps": []
        }
    except json.JSONDecodeError:
        logger.warning("checker JSON parse failed, using stub")
        return _stub_checker(claims, evidence)


def _stub_checker(claims: list[dict], evidence: list[dict]) -> dict[str, Any]:
    """无 LLM 时的 Stub 返回"""
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "success",
        "data": {
            "coverage": 0.5,
            "credibility_issues": [],
            "conflicts": [],
            "gaps": ["需要配置 LLM API key 以获得真实核查"],
            "recommendations": ["请配置 LLM API key 以启用事实核查功能"]
        },
        "errors": [],
        "gaps": ["需要配置 LLM API key 以获得真实核查"]
    }


def _error_checker(error: str) -> dict[str, Any]:
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "error",
        "data": None,
        "errors": [error],
        "gaps": ["checker 调用失败"]
    }


def writer(analysis: dict, check_result: dict | None, output_format: str = "both") -> dict[str, Any]:
    """
    生成最终交付物：Markdown 报告 + PPT 大纲 JSON + 逐页内容 JSON。

    Args:
        analysis (dict): Analyst 输出
        check_result (dict, optional): Checker 输出
        output_format (str): markdown / ppt / both

    Returns:
        dict: {
            "task_id": str,
            "status": "success" | "error",
            "data": {
                "report_md": str,           # Markdown 报告
                "ppt_outline": dict,        # PPT 大纲 JSON
                "slides": list[dict]         # 逐页内容 JSON
            },
            "errors": list[str],
            "gaps": list[str]
        }
    """
    # 无 LLM key → 返回 stub
    if not settings.deepseek_api_key and not settings.openai_api_key and not settings.qwen_api_key:
        return _stub_writer(analysis, check_result)

    try:
        return _call_writer(analysis, check_result, output_format)
    except Exception as e:
        logger.error("writer LLM call failed", error=str(e))
        return _error_writer(str(e))


def _call_writer(analysis: dict, check_result: dict | None, output_format: str) -> dict[str, Any]:
    """调用 LLM 生成报告（同步包装）"""
    return asyncio.run(_async_writer(analysis, check_result, output_format))


async def _build_ppt_content(
    analysis: dict,
    check_result: dict | None,
    llm
) -> tuple[dict, list[dict]]:
    """构建 PPT 大纲和逐页内容（LLM 驱动）"""

    # 提取 analyst 数据
    data = analysis.get("data", {}) if isinstance(analysis, dict) else {}
    trends = data.get("trends", [])
    opportunities = data.get("opportunities", [])
    risks = data.get("risks", [])
    summary = data.get("summary", "")
    audience = data.get("audience", "行业研究者")

    # 提取 checker 数据
    check_data = check_result.get("data", {}) if isinstance(check_result, dict) and check_result else {}
    gaps = check_data.get("gaps", [])
    recommendations = check_data.get("recommendations", [])

    # 格式化数据
    trends_text = "\n".join([
        f"- **{t.get('topic', '未知趋势')}**：{t.get('description', '')} (置信度: {t.get('confidence', 0):.0%})"
        for t in trends
    ]) if trends else "暂无趋势数据"

    opportunities_text = "\n".join([
        f"- **{o.get('title', '未知机会')}**：{o.get('description', '')} (证据数: {o.get('evidence_count', 0)})"
        for o in opportunities
    ]) if opportunities else "暂无机会数据"

    risks_text = "\n".join([
        f"- **{r.get('title', '未知风险')}**：{r.get('description', '')} (严重程度: {r.get('severity', 'unknown')})"
        for r in risks
    ]) if risks else "暂无风险数据"

    gaps_text = "\n".join([f"- {g}" for g in gaps]) if gaps else "暂无缺口"
    recommendations_text = "\n".join([f"- {r}" for r in recommendations]) if recommendations else "暂无建议"

    messages = [
        {
            "role": "system",
            "content": f"""你是一个专业的 PPT 设计师。根据以下研究分析数据，生成一份结构完整的 PPT 大纲。

要求：
1. 生成 8-15 页 PPT
2. 页面结构：封面、目录、趋势分析（2-3页）、机会分析（2页）、风险分析（1-2页）、核查结果（1页）、建议（1页）、结语
3. 每页包含：page、title、bullets（3-5条）、speaker_notes（100字内）、sources（留空）
4. 使用中文撰写
5. audience: {audience}

分析数据：
趋势分析：
{trends_text}

机会分析：
{opportunities_text}

风险分析：
{risks_text}

核查结果：
{gaps_text}

建议：
{recommendations_text}

请以 JSON 格式输出 PPT 大纲，不要包含其他内容：
{{
  "title": "PPT 标题",
  "audience": "受众",
  "total_pages": 页数,
  "estimated_duration_minutes": 预估分钟数,
  "slides": [
    {{
      "page": 1,
      "title": "页面标题",
      "bullets": ["要点1", "要点2", "要点3"],
      "speaker_notes": "演讲者备注",
      "sources": []
    }}
  ]
}}"""
        },
        {
            "role": "user",
            "content": "请生成 PPT 大纲和逐页内容。"
        }
    ]

    response = await llm.chat(messages)

    try:
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
        else:
            json_str = response.strip()

        ppt_data = json.loads(json_str)

        ppt_outline = {
            "title": ppt_data.get("title", "研究报告"),
            "audience": ppt_data.get("audience", audience),
            "total_pages": ppt_data.get("total_pages", len(ppt_data.get("slides", []))),
            "estimated_duration_minutes": ppt_data.get("estimated_duration_minutes", 20),
            "slides": ppt_data.get("slides", [])
        }

        slides = ppt_outline["slides"]

        return ppt_outline, slides

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("PPT generation failed, using fallback", error=str(e))
        # Fallback: 生成默认 PPT 结构
        return _generate_fallback_ppt(audience)


def _generate_fallback_ppt(audience: str) -> tuple[dict, list[dict]]:
    """生成默认 PPT 结构（LLM 生成失败时 fallback）"""
    slides = [
        {"page": 1, "title": "封面", "bullets": ["研究报告标题", "副标题/日期", "演讲者信息"], "speaker_notes": "开场封面页，介绍研究主题和背景", "sources": []},
        {"page": 2, "title": "目录", "bullets": ["趋势分析", "机会分析", "风险分析", "事实核查", "建议与总结"], "speaker_notes": "目录页，概述报告结构", "sources": []},
        {"page": 3, "title": "趋势分析（一）", "bullets": ["核心趋势一", "核心趋势二", "核心趋势三"], "speaker_notes": "深入分析主要趋势及其影响", "sources": []},
        {"page": 4, "title": "趋势分析（二）", "bullets": ["次要趋势一", "次要趋势二", "趋势预测"], "speaker_notes": "补充分析其他重要趋势", "sources": []},
        {"page": 5, "title": "机会分析（一）", "bullets": ["市场机会一", "市场机会二", "机会优先级"], "speaker_notes": "分析主要市场机会及可行性", "sources": []},
        {"page": 6, "title": "机会分析（二）", "bullets": ["新兴机会", "潜在机会", "机会评估"], "speaker_notes": "补充分析新兴和潜在机会", "sources": []},
        {"page": 7, "title": "风险分析", "bullets": ["主要风险一", "主要风险二", "风险缓解策略"], "speaker_notes": "分析主要风险及应对措施", "sources": []},
        {"page": 8, "title": "事实核查结果", "bullets": ["证据覆盖率", "可信度评估", "缺口与不足"], "speaker_notes": "展示核查结果，指出信息缺口", "sources": []},
        {"page": 9, "title": "建议", "bullets": ["短期建议", "中期建议", "长期建议"], "speaker_notes": "基于分析给出具体行动建议", "sources": []},
        {"page": 10, "title": "结语", "bullets": ["核心结论", "下一步行动", "Q&A"], "speaker_notes": "总结核心观点，开放讨论", "sources": []},
    ]

    ppt_outline = {
        "title": "研究报告",
        "audience": audience,
        "total_pages": len(slides),
        "estimated_duration_minutes": 25,
        "slides": slides
    }

    return ppt_outline, slides


async def _async_writer(analysis: dict, check_result: dict | None, output_format: str) -> dict[str, Any]:
    """调用 LLM 生成 Markdown 报告（async）"""
    from ..llm import create_llm

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model
    )

    # 提取 analyst 数据（兼容 stub 输出）
    data = analysis.get("data", {}) if isinstance(analysis, dict) else {}
    trends = data.get("trends", [])
    opportunities = data.get("opportunities", [])
    risks = data.get("risks", [])
    summary = data.get("summary", "暂无摘要")

    # 提取 checker 数据（兼容 stub 输出）
    check_data = check_result.get("data", {}) if isinstance(check_result, dict) and check_result else {}
    coverage = check_data.get("coverage", 0.0)
    credibility_issues = check_data.get("credibility_issues", [])
    conflicts = check_data.get("conflicts", [])
    gaps = check_data.get("gaps", [])
    recommendations = check_data.get("recommendations", [])

    # 构建 Markdown 报告
    report_md = await _build_markdown_report(
        summary, trends, opportunities, risks,
        coverage, credibility_issues, conflicts, gaps, recommendations, llm
    )

    # PPT 生成（仅当 output_format 为 ppt 或 both 时）
    if output_format in ("ppt", "both"):
        try:
            ppt_outline, slides = await _build_ppt_content(analysis, check_result, llm)
        except Exception as e:
            logger.error("PPT generation failed", error=str(e))
            ppt_outline, slides = {"title": "研究汇报", "pages": []}, []
    else:
        ppt_outline, slides = {"title": "研究汇报", "pages": []}, []

    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "success",
        "data": {
            "report_md": report_md,
            "ppt_outline": ppt_outline,
            "slides": slides
        },
        "errors": [],
        "gaps": []
    }


async def _build_markdown_report(
    summary: str,
    trends: list[dict],
    opportunities: list[dict],
    risks: list[dict],
    coverage: float,
    credibility_issues: list[dict],
    conflicts: list[dict],
    gaps: list[str],
    recommendations: list[str],
    llm
) -> str:
    """构建 Markdown 报告（优先 LLM 生成，fallback 到模板）"""
    # 格式化 trends
    trends_text = ""
    for t in trends:
        topic = t.get("topic", "未知趋势")
        description = t.get("description", "")
        confidence = t.get("confidence", 0.0)
        trends_text += f"### {topic}\n{description}\n来源置信度：{confidence:.0%}\n\n"

    # 格式化 opportunities
    opportunities_text = ""
    for o in opportunities:
        title = o.get("title", "未知机会")
        description = o.get("description", "")
        evidence_count = o.get("evidence_count", 0)
        opportunities_text += f"### {title}\n{description}\n证据数量：{evidence_count}\n\n"

    # 格式化 risks
    risks_text = ""
    for r in risks:
        title = r.get("title", "未知风险")
        description = r.get("description", "")
        severity = r.get("severity", "unknown")
        risks_text += f"### {title}\n{description}\n严重程度：{severity}\n\n"

    # 格式化 credibility_issues
    credibility_text = ""
    for issue in credibility_issues:
        source = issue.get("source", "未知来源")
        issue_desc = issue.get("issue", "")
        credibility_text += f"- {source}: {issue_desc}\n"

    # 格式化 conflicts
    conflicts_text = ""
    for c in conflicts:
        claim_a = c.get("claim_a", "")
        claim_b = c.get("claim_b", "")
        resolution = c.get("resolution", "")
        conflicts_text += f"- 冲突：{claim_a} vs {claim_b} → {resolution}\n"

    # 格式化 gaps
    gaps_text = ""
    for g in gaps:
        gaps_text += f"- 缺口：{g}\n"

    # 格式化 recommendations
    recommendations_text = ""
    for r in recommendations:
        recommendations_text += f"- {r}\n"

    messages = [
        {
            "role": "system",
            "content": """你是一个专业的研究报告撰写专家。根据以下分析数据和核查结果，生成一份结构完整的 Markdown 研究报告。

要求：
1. 报告必须包含：执行摘要、趋势分析、机会分析、风险分析、事实核查结果、建议
2. 使用中文撰写
3. 逻辑清晰，论述有据
4. 不要生成额外的 JSON 或代码块，只输出纯 Markdown 格式

主题：研究主题（根据内容自行推断）

## 执行摘要
{summary}

## 趋势分析
{trends_text}

## 机会分析
{opportunities_text}

## 风险分析
{risks_text}

## 事实核查结果
证据覆盖率：{coverage:.0%}
{credibility_text}
{conflicts_text}
{gaps_text}

## 建议
{recommendations_text}"""
        },
        {
            "role": "user",
            "content": f"请根据以上信息生成研究报告。"
        }
    ]

    response = await llm.chat(messages)

    # 尝试解析是否返回了有效报告
    if response and len(response) > 100 and "#" in response:
        return response
    else:
        # Fallback: 返回基于模板的报告
        return _generate_fallback_report(
            summary, trends_text, opportunities_text, risks_text,
            coverage, credibility_text, conflicts_text, gaps_text, recommendations_text
        )


def _generate_fallback_report(
    summary: str,
    trends_text: str,
    opportunities_text: str,
    risks_text: str,
    coverage: float,
    credibility_text: str,
    conflicts_text: str,
    gaps_text: str,
    recommendations_text: str
) -> str:
    """生成基于模板的报告（LLM 生成失败时 fallback）"""
    report = f"""# 研究报告

## 执行摘要
{summary}

## 趋势分析
{trends_text or "暂无趋势数据"}

## 机会分析
{opportunities_text or "暂无机会数据"}

## 风险分析
{risks_text or "暂无风险数据"}

## 事实核查结果
证据覆盖率：{coverage:.0%}

{credibility_text or "- 暂无可信度问题"}
{conflicts_text or "- 暂无冲突检测"}
{gaps_text or "- 暂无缺口"}

## 建议
{recommendations_text or "- 建议继续收集证据"}
"""
    return report


def _stub_writer(analysis: dict, check_result: dict | None) -> dict[str, Any]:
    """无 LLM 时的 Stub 返回"""
    data = analysis.get("data", {}) if isinstance(analysis, dict) else {}
    summary = data.get("summary", "暂无摘要")
    trends = data.get("trends", [])
    opportunities = data.get("opportunities", [])
    risks = data.get("risks", [])
    audience = data.get("audience", "行业研究者")

    check_data = check_result.get("data", {}) if isinstance(check_result, dict) and check_result else {}
    coverage = check_data.get("coverage", 0.0)
    recommendations = check_data.get("recommendations", [])

    # 构建简单的 stub 报告
    trends_text = "\n".join([f"- **{t.get('topic', '未知趋势')}**：{t.get('description', '')}" for t in trends]) if trends else "暂无趋势数据"
    opportunities_text = "\n".join([f"- **{o.get('title', '未知机会')}**：{o.get('description', '')}" for o in opportunities]) if opportunities else "暂无机会数据"
    risks_text = "\n".join([f"- **{r.get('title', '未知风险')}**：{r.get('description', '')} (严重程度: {r.get('severity', 'unknown')})" for r in risks]) if risks else "暂无风险数据"
    recommendations_text = "\n".join([f"- {r}" for r in recommendations]) if recommendations else "- 暂无建议"

    report_md = f"""# 研究报告（Stub 模式）

> ⚠️ 当前处于 Stub 模式，建议配置 LLM API key 以获得真实分析报告。

## 执行摘要
{summary}

## 趋势分析
{trends_text}

## 机会分析
{opportunities_text}

## 风险分析
{risks_text}

## 事实核查结果
证据覆盖率：{coverage:.0%}

## 建议
{recommendations_text}
"""

    # 生成 fallback PPT
    ppt_outline, slides = _generate_fallback_ppt(audience)

    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "success",
        "data": {
            "report_md": report_md,
            "ppt_outline": ppt_outline,
            "slides": slides
        },
        "errors": [],
        "gaps": ["writer 处于 stub 模式，需要配置 LLM API key"]
    }


def _error_writer(error: str) -> dict[str, Any]:
    return {
        "task_id": str(uuid.uuid4())[:8],
        "status": "error",
        "data": None,
        "errors": [error],
        "gaps": ["writer 调用失败"]
    }