import json
from typing import Any

from core import get_logger, settings
from retrieval import MultiPathRetriever
from vectorstore import MilvusStore

from ..templates import load_prompt

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
    """Analyze query to determine intent and strategy."""
    query = state.get("query", "")
    logger.info("analyzing_query", query=query)

    # For MVP, we do simple analysis
    # Full version would use LLM for structured output
    parsed = {
        "intent": "news_query",
        "keywords": query.split(),
        "language": "en" if any(c.isascii() and c.isalpha() for c in query) else "zh",
    }

    return {"parsed_query": parsed, "search_strategy": "multi_path"}


async def retrieve(state: dict) -> dict:
    """Execute multi-path retrieval."""
    query = state.get("query", "")
    top_k = state.get("top_k", 5)

    logger.info("retrieving", query=query, top_k=top_k)

    store = MilvusStore()
    retriever = MultiPathRetriever(store)

    results = retriever.retrieve(query, top_k=top_k * 2)  # Get more for re-ranking

    return {
        "retrieval_results": results,
        "filtered_results": results[:top_k],
    }


async def evaluate_relevance(state: dict) -> dict:
    """Evaluate retrieval results relevance."""
    results = state.get("retrieval_results", [])
    query = state.get("query", "")

    if not results:
        logger.warning("no_results_to_evaluate")
        return {"error": "No results to evaluate"}

    # Format context for evaluation
    context = format_context(results[:5])  # Top 5 for evaluation

    # For MVP, use simple heuristic
    # Full version would use LLM
    avg_score = sum(r.get("score", 0) for r in results[:5]) / min(5, len(results))
    relevance = "HIGH" if avg_score > 0.6 else "MEDIUM" if avg_score > 0.4 else "LOW"

    logger.info("relevance_evaluated",
        query=query,
        relevance=relevance,
        avg_score=avg_score,
    )

    return {
        "reflection": {
            "relevance": relevance,
            "avg_score": avg_score,
            "reasoning": f"Average score: {avg_score:.3f}",
        }
    }


async def generate_answer(state: dict) -> dict:
    """Generate answer using LLM with retrieved context."""
    from ..llm import create_llm

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
            from ..llm.cache import CachedLLM
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