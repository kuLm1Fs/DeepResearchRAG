from langgraph.graph import StateGraph, END

from .state import AgentState
from .nodes import analyze_query, retrieve, evaluate_relevance, generate_answer, self_reflect


def should_continue(state: AgentState) -> str:
    """决定是否继续迭代。"""
    iteration = state.get("iteration", 0)
    reflection = state.get("reflection", {})

    # 最多迭代 3 次
    if iteration >= 3:
        return "end"

    # 如果相关性低，重新检索
    if reflection.get("relevance") == "LOW":
        return "retrieve"

    return "end"


def create_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("analyze_query", analyze_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("evaluate_relevance", evaluate_relevance)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("self_reflect", self_reflect)

    # 设置入口
    graph.set_entry_point("analyze_query")

    # 添加边
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "evaluate_relevance")
    graph.add_conditional_edges("evaluate_relevance", should_continue, {
        "retrieve": "retrieve",
        "end": "generate_answer",
    })
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


async def run_agent(query: str, trace_id: str = "", top_k: int = 5) -> dict:
    """运行 Agent，返回结果。"""
    graph = get_compiled_graph()

    initial_state = {
        "query": query,
        "trace_id": trace_id,
        "top_k": top_k,
        "iteration": 0,
        "error": None,
    }

    result = await graph.ainvoke(initial_state)
    return result