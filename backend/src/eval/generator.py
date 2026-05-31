"""Answer generation for evaluation — runs outside the full agent graph.

Reuses format_context / format_sources / bind_claim_citations from agent.nodes
but calls the LLM directly, skipping analyze_query / plan_retrieval / etc.
Each query costs 1 LLM call (generation only; judge is separate).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core import get_logger

logger = get_logger(__name__)

_cached_llm = None

# Reuse the same prompt template the agent uses
_TEMPLATE_DIR = Path(__file__).parent.parent / "agent" / "templates" / "v1"


def _get_llm():
    global _cached_llm
    if _cached_llm is None:
        from llm import create_llm
        from core.config import settings

        _cached_llm = create_llm(
            provider=settings.llm_provider,
            api_key=settings.deepseek_api_key,
            model=settings.llm_model,
        )
    return _cached_llm


def _load_answer_prompt(query: str, context: str) -> str:
    """Load the generate_answer prompt template and fill variables."""
    template_path = _TEMPLATE_DIR / "generate_answer.txt"
    template = template_path.read_text(encoding="utf-8")
    return template.replace("{context}", context).replace("{query}", query)


async def generate_answer_only(
    query: str,
    retrieval_results: list[dict[str, Any]],
) -> tuple[str, list[dict], list[dict]]:
    """Generate an answer + bind citations without running the full agent graph.

    Returns (answer_text, sources, citations).
    """
    from agent.nodes import format_context, format_sources, bind_claim_citations

    if not retrieval_results:
        return "No relevant articles found.", [], []

    context = format_context(retrieval_results)
    sources = format_sources(retrieval_results)

    llm = _get_llm()
    prompt = _load_answer_prompt(query, context)

    try:
        answer = await llm.chat([{"role": "user", "content": prompt}])
    except Exception as e:
        logger.error("eval_answer_generation_failed", error=str(e))
        return f"Error generating answer: {e}", sources, []

    citations = bind_claim_citations(answer, sources)

    return answer, sources, citations
