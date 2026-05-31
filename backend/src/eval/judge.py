"""LLM-as-Judge for evaluating answer quality.

Provides Faithfulness (answer grounded in sources) and
Relevance (answer addresses the query) scoring on a 1-5 scale.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core import get_logger

logger = get_logger(__name__)

_cached_llm = None

FAITHFULNESS_PROMPT = """You are evaluating whether an answer is grounded in the provided sources.

User Question: {query}

Retrieved Sources:
{sources}

Generated Answer:
{answer}

Rate the faithfulness on a scale of 1-5:
1 = Answer contradicts or fabricates information not in sources
2 = Answer has significant unsupported claims
3 = Answer is mostly supported but has some unsupported details
4 = Answer is well-supported with minor extrapolations
5 = Answer is completely grounded in the provided sources

Return ONLY a JSON object:
{{"score": <1-5>, "reasoning": "<brief explanation>"}}"""

RELEVANCE_PROMPT = """You are evaluating whether an answer addresses the user's question.

User Question: {query}

Generated Answer:
{answer}

Rate the relevance on a scale of 1-5:
1 = Answer is completely off-topic
2 = Answer is tangentially related but doesn't address the question
3 = Answer partially addresses the question
4 = Answer mostly addresses the question with minor gaps
5 = Answer fully and directly addresses the question

Return ONLY a JSON object:
{{"score": <1-5>, "reasoning": "<brief explanation>"}}"""

CORRECTNESS_PROMPT = """You are evaluating whether a generated answer is correct compared to a gold standard answer.

User Question: {query}

Gold Standard Answer:
{gold_answer}

Generated Answer:
{answer}

Rate the correctness on a scale of 1-5:
1 = Completely wrong or contradicts the gold answer
2 = Major factual errors, mostly incorrect
3 = Partially correct, some key facts right but missing or wrong on others
4 = Mostly correct with minor inaccuracies or omissions
5 = Fully correct, matches the gold answer in all key facts

Return ONLY a JSON object:
{{"score": <1-5>, "reasoning": "<brief explanation>"}}"""


def _get_llm():
    """Lazy-init singleton LLM for judge calls."""
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


def _parse_score(text: str) -> dict[str, Any]:
    """Extract score and reasoning from LLM response, with fallback."""
    try:
        # Try direct JSON parse
        data = json.loads(text.strip())
        return {"score": int(data["score"]), "reasoning": data.get("reasoning", "")}
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    # Fallback: extract JSON from markdown code block
    match = re.search(r"\{[^}]+\}", text)
    if match:
        try:
            data = json.loads(match.group())
            return {"score": int(data["score"]), "reasoning": data.get("reasoning", "")}
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    logger.warning("judge_parse_failed", raw=text[:200])
    return {"score": 0, "reasoning": f"Failed to parse judge response: {text[:100]}"}


def _format_sources_for_judge(sources: list[dict]) -> str:
    """Format sources as numbered text blocks for the judge prompt."""
    parts = []
    for i, s in enumerate(sources[:10], 1):
        title = s.get("title", "Unknown")
        content = s.get("content", "")[:300]
        source = s.get("source", "")
        parts.append(f"[{i}] {title} ({source}): {content}")
    return "\n\n".join(parts) if parts else "No sources provided."


class EvalJudge:
    """LLM-as-Judge for evaluating answer quality."""

    async def judge_faithfulness(
        self, query: str, answer: str, sources: list[dict]
    ) -> dict[str, Any]:
        """Rate how well the answer is grounded in the provided sources (1-5)."""
        llm = _get_llm()
        prompt = FAITHFULNESS_PROMPT.format(
            query=query,
            sources=_format_sources_for_judge(sources),
            answer=answer[:2000],
        )
        try:
            result = await llm.chat([{"role": "user", "content": prompt}])
            return _parse_score(result)
        except Exception as e:
            logger.error("faithfulness_judge_failed", error=str(e))
            return {"score": 0, "reasoning": f"Judge call failed: {e}"}

    async def judge_relevance(self, query: str, answer: str) -> dict[str, Any]:
        """Rate how well the answer addresses the query (1-5)."""
        llm = _get_llm()
        prompt = RELEVANCE_PROMPT.format(query=query, answer=answer[:2000])
        try:
            result = await llm.chat([{"role": "user", "content": prompt}])
            return _parse_score(result)
        except Exception as e:
            logger.error("relevance_judge_failed", error=str(e))
            return {"score": 0, "reasoning": f"Judge call failed: {e}"}

    async def judge_correctness(
        self, query: str, answer: str, gold_answer: str
    ) -> dict[str, Any]:
        """Compare generated answer against gold standard answer (1-5)."""
        llm = _get_llm()
        prompt = CORRECTNESS_PROMPT.format(
            query=query, answer=answer[:2000], gold_answer=gold_answer[:2000]
        )
        try:
            result = await llm.chat([{"role": "user", "content": prompt}])
            return _parse_score(result)
        except Exception as e:
            logger.error("correctness_judge_failed", error=str(e))
            return {"score": 0, "reasoning": f"Judge call failed: {e}"}
