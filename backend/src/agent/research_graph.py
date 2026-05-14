"""Deep Research Supervisor + Multi-Tool 工作流"""
from typing import Literal

from langgraph.graph import END, StateGraph

from .research_state import ResearchState
from .research_tools import planner, retriever, analyst, checker, writer
from ..core import get_logger

logger = get_logger(__name__)


def should_continue(state: ResearchState) -> Literal["retriever", "writer"]:
    """检查是否需要补充检索。"""
    check_result = state.get("check_result")
    if check_result and check_result.get("gaps"):
        if len(check_result["gaps"]) > 0 and state.get("tool_call_count", 0) < state.get("max_tool_calls", 20):
            return "retriever"
    return "writer"


def create_research_graph():
    """构建 Supervisor 工作流图。"""
    graph = StateGraph(ResearchState)

    # 节点
    graph.add_node("planner", lambda state: {"current_step": "planner", "plan": _call_planner(state)})
    graph.add_node("retriever", lambda state: _call_retriever(state))
    graph.add_node("analyst", lambda state: {"current_step": "analyst", "analysis": _call_analyst(state)})
    graph.add_node("checker", lambda state: {"current_step": "checker", "check_result": _call_checker(state), "gaps": _call_checker(state).get("gaps", [])})
    graph.add_node("writer", lambda state: {"current_step": "writer", "final_output": _call_writer(state)})

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


async def run_research(query: str, user_id: str | None = None, company_id: str | None = None) -> dict:
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
    }

    result = await graph.ainvoke(initial_state)
    return result.get("final_output", {})


# ---- Tool 调用包装 ----
def _call_planner(state: ResearchState) -> dict:
    result = planner(query=state["query"], user_id=state.get("user_id"))
    return result.get("data", {})


def _call_retriever(state: ResearchState) -> dict:
    sub_questions = state.get("sub_questions", []) or [state["query"]]
    result = retriever(sub_questions=sub_questions, user_id=state.get("user_id"))
    return {
        "evidence": result.get("data", {}).get("evidence", []),
        "tool_call_count": state.get("tool_call_count", 0) + 1
    }


def _call_analyst(state: ResearchState) -> dict:
    result = analyst(evidence=state.get("evidence", []))
    return result.get("data", {})


def _call_checker(state: ResearchState) -> dict:
    claims = state.get("analysis", {}).get("claims", [])
    result = checker(claims=claims, evidence=state.get("evidence", []))
    return result.get("data", {})


def _call_writer(state: ResearchState) -> dict:
    result = writer(
        analysis=state.get("analysis", {}),
        check_result=state.get("check_result")
    )
    return result.get("data", {})