"""Deep Research Supervisor + Multi-Tool 工作流"""
from typing import Literal

from langgraph.graph import END, StateGraph

from core import get_logger

from .research_state import ResearchState
from .research_tools import aplanner, retriever, aanalyst, achecker, awriter

logger = get_logger(__name__)


async def notify_step(state: ResearchState, step: str) -> None:
    callback = state.get("on_step")
    if callback is None:
        return
    await callback(step, state)


def should_continue(state: ResearchState) -> Literal["retriever", "writer"]:
    """检查是否需要补充检索。"""
    check_result = state.get("check_result")
    gaps = check_result.get("gaps", []) if check_result else []
    actionable_gaps = [
        gap for gap in gaps
        if "配置" not in gap and "API key" not in gap and "证据为空" not in gap
    ]
    if actionable_gaps:
        if state.get("tool_call_count", 0) < state.get("max_tool_calls", 20):
            return "retriever"
    return "writer"


def create_research_graph():
    """构建 Supervisor 工作流图。"""
    graph = StateGraph(ResearchState)

    # 节点
    graph.add_node("planner", _planner_node)
    graph.add_node("retriever", _retriever_node)
    graph.add_node("analyst", _analyst_node)
    graph.add_node("checker", _checker_node)
    graph.add_node("writer", _writer_node)

    # 入口
    graph.set_entry_point("planner")

    # 条件边
    graph.add_edge("planner", "retriever")
    graph.add_edge("retriever", "analyst")
    graph.add_edge("analyst", "checker")
    # checker 有缺口 → retriever 补充检索（最多 MAX_TOOL_CALLS 次）
    # 否则 → writer
    graph.add_conditional_edges(
        "checker",
        should_continue,
        {
            "retriever": "retriever",
            "writer": "writer"
        }
    )
    graph.add_edge("writer", END)

    return graph.compile()


async def run_research(
    query: str,
    user_id: str | None = None,
    company_id: str | None = None,
    on_step=None,
    return_state: bool = False,
) -> dict:
    """
    执行完整研究流程。

    Args:
        query (str): 用户问题
        user_id (str, optional): 用户 ID
        company_id (str, optional): 公司 ID

    Returns:
        dict: 最终输出 {report_md, ppt_outline, slides}
    """
    graph = create_research_graph()
    initial_state: ResearchState = {
        "query": query,
        "task_id": "",
        "user_id": user_id or "",
        "company_id": company_id,
        "current_step": "planner",
        "tool_call_count": 0,
        "max_tool_calls": 20,
        "plan": None,
        "sub_questions": [],
        "evidence": [],
        "analysis": None,
        "check_result": None,
        "gaps": [],
        "conflicts": [],
        "final_output": None,
        "failed_step": None,
        "retry_count": 0,
        "error": None,
        "on_step": on_step,
    }

    result = await graph.ainvoke(initial_state)
    if return_state:
        return result
    return result.get("final_output", {})


# ---- Tool 调用包装 ----
async def _planner_node(state: ResearchState) -> dict:
    await notify_step(state, "planner")
    plan = await _call_planner(state)
    sub_questions = plan.get("sub_questions") or plan.get("research_questions") or []
    return {
        "current_step": "planner",
        "plan": plan,
        "sub_questions": sub_questions,
    }


async def _call_planner(state: ResearchState) -> dict:
    result = await aplanner(query=state["query"], user_id=state.get("user_id"))
    return result.get("data", {})


def _call_retriever(state: ResearchState) -> dict:
    if state.get("gaps") and state.get("tool_call_count", 0) > 0:
        sub_questions = state.get("gaps", [])
    else:
        sub_questions = state.get("sub_questions", []) or [state["query"]]

    result = retriever(sub_questions=sub_questions, user_id=state.get("user_id"))
    existing = state.get("evidence", [])
    new_evidence = result.get("data", {}).get("evidence", [])
    merged = _merge_evidence(existing, new_evidence)
    return {
        "current_step": "retriever",
        "evidence": merged,
        "tool_call_count": state.get("tool_call_count", 0) + 1
    }


async def _retriever_node(state: ResearchState) -> dict:
    await notify_step(state, "retriever")
    return _call_retriever(state)


async def _analyst_node(state: ResearchState) -> dict:
    await notify_step(state, "analyst")
    return {"current_step": "analyst", "analysis": await _call_analyst(state)}


async def _call_analyst(state: ResearchState) -> dict:
    result = await aanalyst(evidence=state.get("evidence", []))
    return result.get("data", {})


async def _call_checker(state: ResearchState) -> dict:
    claims = state.get("analysis", {}).get("claims", [])
    result = await achecker(claims=claims, evidence=state.get("evidence", []))
    return result.get("data", {})


async def _checker_node(state: ResearchState) -> dict:
    await notify_step(state, "checker")
    check_result = await _call_checker(state)
    return {
        "current_step": "checker",
        "check_result": check_result,
        "gaps": check_result.get("gaps", []),
        "conflicts": check_result.get("conflicts", []),
    }


async def _writer_node(state: ResearchState) -> dict:
    await notify_step(state, "writer")
    return {"current_step": "writer", "final_output": await _call_writer(state)}


async def _call_writer(state: ResearchState) -> dict:
    result = await awriter(
        analysis=state.get("analysis", {}),
        check_result=state.get("check_result")
    )
    return result.get("data", {})


def _merge_evidence(existing: list[dict], new_evidence: list[dict]) -> list[dict]:
    merged = []
    seen = set()

    for item in [*existing, *new_evidence]:
        key = item.get("url") or item.get("title") or item.get("content", "")[:200]
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged
