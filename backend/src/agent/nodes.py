import json
from typing import Any, AsyncIterator

from core import get_logger, settings
from retrieval import MultiPathRetriever
from vectorstore import MilvusStore

from .templates import load_prompt

logger = get_logger(__name__)


def format_context(results: list[dict], max_length: int = 2000) -> str:
    """Format retrieval results as context for LLM."""
    if not results:
        return "No relevant articles found."

    context_parts = []
    current_length = 0

    for i, r in enumerate(results, 1):
        title = r.get("title", "Unknown")
        content = r.get("content", "")
        source = r.get("source", "")
        category = r.get("category", "")

        # Truncate content if needed
        if len(content) > 300:
            content = content[:300] + "..."

        part = f"[{i}] {title} ({category}, {source}): {content}"
        part_length = len(part)

        if current_length + part_length > max_length:
            break

        context_parts.append(part)
        current_length += part_length

    return "\n\n".join(context_parts)


def format_sources(results: list[dict]) -> list[dict]:
    """Format retrieval results as sources for citation."""
    sources = []
    for r in results:
        sources.append({
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "source": r.get("source", ""),
            "category": r.get("category", ""),
            "score": r.get("score", 0),
        })
    return sources


async def analyze_query(state: dict) -> dict:
    """用 LLM 分析查询意图、关键词和子查询。"""
    from llm import create_llm

    query = state.get("query", "")
    logger.info("analyzing_query", query=query)

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model,
    )

    prompt = load_prompt("analyze_query", query=query)
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.chat(messages)
        parsed = json.loads(response.strip())
    except Exception as e:
        logger.warning("analyze_query_llm_failed", error=str(e))
        # fallback
        parsed = {
            "intent": "factual",
            "rewritten_query": query,
            "sub_queries": [],
            "keywords": query.split(),
        }

    # 构建检索 query 列表
    search_queries = [parsed.get("rewritten_query", query)]
    search_queries.extend(parsed.get("sub_queries", []))

    return {
        "parsed_query": parsed,
        "search_queries": search_queries,
    }


async def plan_retrieval(state: dict) -> dict:
    """根据分析结果规划检索策略。"""
    parsed = state.get("parsed_query", {})
    query = state.get("query", "")
    top_k = state.get("top_k", 5)

    search_queries = state.get("search_queries", [query])

    # 根据意图类型调整检索参数
    intent = parsed.get("intent", "factual")
    if intent == "analysis":
        per_query = 5  # 分析类需要更多材料
        total = top_k * 2
    elif intent == "comparison":
        per_query = 4
        total = top_k * 2
    else:
        per_query = 3
        total = top_k

    logger.info(
        "planning_retrieval",
        intent=intent,
        num_queries=len(search_queries),
        per_query=per_query,
        total=total,
    )

    return {
        "search_plan": {
            "queries": search_queries,
            "per_query": per_query,
            "total": total,
        },
    }


async def retrieve(state: dict) -> dict:
    """执行多路多轮检索。"""
    search_plan = state.get("search_plan", {})
    queries = search_plan.get("queries", [state.get("query", "")])
    per_query = search_plan.get("per_query", 3)
    total = search_plan.get("total", state.get("top_k", 5))

    logger.info("retrieving", num_queries=len(queries), per_query=per_query, total=total)

    store = MilvusStore()
    retriever = MultiPathRetriever(store)

    all_results = []
    seen_titles = set()

    for q in queries:
        results = await retriever.retrieve(q, top_k=per_query)
        for r in results:
            title = r.get("title", "")
            if title not in seen_titles:
                seen_titles.add(title)
                all_results.append(r)

    # 按 score 排序，取 top total
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_results = all_results[:total]

    logger.info("retrieval_complete", total_results=len(all_results), returned=len(top_results))

    return {
        "retrieval_results": top_results,
        "filtered_results": top_results[:state.get("top_k", 5)],
    }


async def evaluate_relevance(state: dict) -> dict:
    """用 LLM 评估检索结果质量。"""
    from llm import create_llm

    results = state.get("retrieval_results", [])
    query = state.get("query", "")

    if not results:
        return {
            "reflection": {
                "relevance": "LOW",
                "coverage": 0,
                "action": "proceed",
                "gaps": ["No results"],
            },
        }

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model,
    )

    context = format_context(results[:5])
    prompt = load_prompt("evaluate_relevance", query=query, context=context)
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.chat(messages)
        reflection = json.loads(response.strip())
    except Exception as e:
        logger.warning("evaluate_relevance_llm_failed", error=str(e))
        # fallback
        avg_score = sum(r.get("score", 0) for r in results[:5]) / min(5, len(results))
        relevance = "HIGH" if avg_score > 0.6 else "MEDIUM" if avg_score > 0.4 else "LOW"
        reflection = {
            "relevance": relevance,
            "coverage": int(avg_score * 100),
            "gaps": [],
            "action": "proceed",
            "re_search_query": "",
        }

    logger.info(
        "relevance_evaluated",
        relevance=reflection.get("relevance"),
        coverage=reflection.get("coverage"),
        action=reflection.get("action"),
    )

    return {"reflection": reflection}


async def re_search(state: dict) -> dict:
    """用补充 query 进行额外检索，合并结果。"""
    reflection = state.get("reflection", {})
    re_search_query = reflection.get("re_search_query", "")

    logger.info("re_searching", query=re_search_query)

    if not re_search_query:
        return {"re_search_count": state.get("re_search_count", 0) + 1}

    store = MilvusStore()
    retriever = MultiPathRetriever(store)

    new_results = await retriever.retrieve(re_search_query, top_k=5)

    # 合并去重
    existing = {r.get("title") for r in state.get("retrieval_results", [])}
    combined = list(state.get("retrieval_results", []))
    for r in new_results:
        if r.get("title") not in existing:
            combined.append(r)

    combined.sort(key=lambda x: x.get("score", 0), reverse=True)

    logger.info("re_search_complete", new_results=len(new_results), combined=len(combined))

    return {
        "retrieval_results": combined[:15],
        "filtered_results": combined[:state.get("top_k", 5)],
        "re_search_count": state.get("re_search_count", 0) + 1,
    }


async def generate_answer(state: dict) -> dict:
    """Generate answer using LLM with retrieved context.

    NOTE: Streaming support requires refactoring the agent workflow to return
    an async generator instead of a dict. The current implementation collects
    the full answer before returning. For true streaming, the SSE endpoint would
    need to yield from stream_chat() directly.
    """
    from llm import create_llm

    query = state.get("query", "")
    results = state.get("retrieval_results", [])

    if not results:
        return {"answer": "I couldn't find any relevant articles to answer your question.", "sources": []}

    # Create LLM client
    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model,
    )

    # Format context and sources
    context = format_context(results)
    sources = format_sources(results)

    # Load prompt template
    prompt = load_prompt("generate_answer", query=query, context=context)

    # Generate answer
    messages = [{"role": "user", "content": prompt}]

    try:
        if settings.llm_cache:
            from llm.cache import CachedLLM
            cached_llm = CachedLLM(llm, cache_dir=settings.llm_cache_dir / settings.llm_provider)
            answer = await cached_llm.chat(messages)
        else:
            answer = await llm.chat(messages)
    except Exception as e:
        logger.error("answer_generation_failed", error=str(e))
        return {"answer": f"Failed to generate answer: {e}", "sources": sources}

    return {"answer": answer, "sources": sources}


async def self_reflect(state: dict) -> dict:
    """Self-reflection on generated answer quality."""
    answer = state.get("answer", "")
    query = state.get("query", "")
    sources = state.get("sources", [])

    if not answer or answer.startswith("Failed"):
        return {"reflection": {"quality": "POOR", "issues": ["Answer generation failed"]}}

    # Simple heuristic check for MVP
    issues = []
    if len(answer) < 50:
        issues.append("Answer too short")
    if not any(c.isalpha() for c in answer):
        issues.append("Answer contains no text")

    quality = "GOOD" if not issues else "FAIR" if len(issues) == 1 else "POOR"

    return {
        "reflection": {
            "quality": quality,
            "issues": issues,
        }
    }


async def generate_answer_stream(state: dict) -> AsyncIterator[str]:
    """流式生成回答，逐 token 产出。

    与 generate_answer() 不同，此函数返回 AsyncIterator[str]，
    用于 SSE 实时流式输出。
    """
    from llm import create_llm
    from llm.cache import CachedLLM

    query = state.get("query", "")
    results = state.get("retrieval_results", [])

    if not results:
        yield "I couldn't find any relevant articles to answer your question."
        return

    llm = create_llm(
        provider=settings.llm_provider,
        api_key=getattr(settings, f"{settings.llm_provider}_api_key"),
        model=settings.llm_model,
    )

    context = format_context(results)
    prompt = load_prompt("generate_answer", query=query, context=context)
    messages = [{"role": "user", "content": prompt}]

    try:
        if settings.llm_cache:
            cached_llm = CachedLLM(llm, cache_dir=settings.llm_cache_dir / settings.llm_provider)
            # 缓存模式下仍然走 stream_chat，CachedLLM 的 chat 是缓存的，stream 是实时的
            async for token in cached_llm.stream_chat(messages):
                yield token
        else:
            async for token in llm.stream_chat(messages):
                yield token
    except Exception as e:
        logger.error("stream_answer_generation_failed", error=str(e))
        yield f"\n\n[Error: {e}]"
