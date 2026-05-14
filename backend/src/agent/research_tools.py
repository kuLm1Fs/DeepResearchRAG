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
    return {
        "task_id": task_id,
        "status": "success",
        "data": {
            "trends": [],
            "opportunities": [],
            "risks": [],
            "summary": "证据不足，无法生成分析（Stub）"
        },
        "errors": [],
        "gaps": ["需要真实证据数据才能生成分析"]
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
    return {
        "task_id": task_id,
        "status": "success",
        "data": {
            "coverage": 0.0,
            "credibility_issues": [],
            "conflicts": [],
            "gaps": ["缺少证据数据"],
            "recommendations": ["请先导入 ai_industry_articles 数据"]
        },
        "errors": [],
        "gaps": []
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
    task_id = str(uuid.uuid4())[:8]
    return {
        "task_id": task_id,
        "status": "success",
        "data": {
            "report_md": "# 研究报告（Stub）\n\n证据不足，内容待补充。",
            "ppt_outline": {"title": "研究汇报", "pages": []},
            "slides": []
        },
        "errors": [],
        "gaps": ["需要真实分析数据"]
    }