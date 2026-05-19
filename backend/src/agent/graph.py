from typing import AsyncIterator

from langgraph.graph import END, StateGraph

from core import get_logger

from .state import AgentState
from .nodes import (
    analyze_query,
    plan_retrieval,
    retrieve,
    evaluate_relevance,
    generate_answer,
    generate_answer_stream,
    self_reflect,
    re_search,
    format_sources,
    compare_sources,
)

logger = get_logger(__name__)


def build_initial_state(
    query: str,
    trace_id: str = "",
    top_k: int = 5,
    use_history: bool = False,
    history: list[dict] | None = None,
) -> AgentState:
    """Build a consistent initial state for all agent entrypoints."""
    return {
        "query": query,
        "trace_id": trace_id,
        "top_k": top_k,
        "use_history": use_history,
        "conversation_history": history or [],
        "iteration": 0,
        "error": None,
        "re_search_count": 0,
    }


def should_research(state: AgentState) -> str:
    """判断是否需要补检索。"""
    reflection = state.get("retrieval_evaluation") or state.get("reflection", {})
    action = reflection.get("action", "proceed")
    # 最多补检索 1 次
    re_search_count = state.get("re_search_count", 0)

    if action in ("re_search", "expand") and re_search_count < 1:
        logger.info("should_research", action=action, re_search_count=re_search_count)
        return "re_search"
    return "proceed"


async def prepare_answer_state(state: AgentState) -> AgentState:
    """Run the shared pre-generation orchestration.

    Both streaming and non-streaming responses must pass through the same
    retrieval planning, evaluation, optional re-search, and source comparison
    steps before answer generation begins.
    """
    working_state: AgentState = dict(state)

    for node in (analyze_query, plan_retrieval, retrieve):
        working_state.update(await node(working_state))

    while True:
        working_state.update(await evaluate_relevance(working_state))
        if should_research(working_state) != "re_search":
            break
        working_state.update(await re_search(working_state))

    working_state.update(await compare_sources(working_state))
    return working_state


def create_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("analyze_query", analyze_query)
    graph.add_node("compare_sources", compare_sources)
    graph.add_node("plan_retrieval", plan_retrieval)
    graph.add_node("retrieve", retrieve)
    graph.add_node("evaluate_relevance", evaluate_relevance)
    graph.add_node("re_search", re_search)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("self_reflect", self_reflect)

    # 设置入口
    graph.set_entry_point("analyze_query")

    # 添加边
    graph.add_edge("analyze_query", "plan_retrieval")
    graph.add_edge("plan_retrieval", "retrieve")
    graph.add_edge("retrieve", "evaluate_relevance")
    graph.add_conditional_edges(
        "evaluate_relevance",
        should_research,
        {
            "re_search": "re_search",
            "proceed": "compare_sources",
        },
    )
    graph.add_edge("re_search", "evaluate_relevance")
    graph.add_edge("compare_sources", "generate_answer")
    graph.add_edge("generate_answer", "self_reflect")
    graph.add_edge("self_reflect", END)

    return graph


# 编译图
compiled_graph = None


def get_compiled_graph():
    global compiled_graph
    if compiled_graph is None:
        graph = create_agent_graph()
        compiled_graph = graph.compile()
    return compiled_graph


async def run_agent(query: str, trace_id: str = "", top_k: int = 5, use_history: bool = False, history: list[dict] = None) -> dict:
    """运行 Agent，返回结果。"""
    graph = get_compiled_graph()
    initial_state = build_initial_state(
        query=query,
        trace_id=trace_id,
        top_k=top_k,
        use_history=use_history,
        history=history,
    )
    return await graph.ainvoke(initial_state)


async def run_agent_stream(query: str, trace_id: str = "", top_k: int = 5) -> AsyncIterator[dict]:
    """流式运行 Agent。

    产出顺序：
    1. {"type": "sources", "data": [...]}  — 检索完成后的来源
    2. {"type": "token", "data": "..."}     — 逐 token 产出
    3. {"type": "done", "data": {...}}      — 完成
    """
    sources = []
    answer_parts = []

    state = build_initial_state(query=query, trace_id=trace_id, top_k=top_k)

    try:
        state = await prepare_answer_state(state)

        sources = format_sources(state.get("retrieval_results", []))
        yield {"type": "sources", "data": sources}

        # 流式生成
        async for token in generate_answer_stream(state):
            answer_parts.append(token)
            yield {"type": "token", "data": token}
    except Exception as e:
        logger.error("stream_agent_failed", error=str(e))
        yield {"type": "error", "data": str(e)}

    yield {
        "type": "done",
        "data": {
            "answer": "".join(answer_parts),
            "sources": sources,
            "trace_id": trace_id,
        },
    }
