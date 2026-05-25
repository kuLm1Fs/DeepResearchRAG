import json
import re
from typing import Any, AsyncIterator

from core import get_logger

from .runtime import AgentRuntime
from .schemas import QueryAnalysis, RetrievalEvaluation
from .templates import load_prompt

logger = get_logger(__name__)


def get_runtime(state: dict) -> AgentRuntime:
    return state.get("runtime") or AgentRuntime()


def get_llm(state: dict):
    return get_runtime(state).create_llm()


def get_retriever(state: dict):
    return get_runtime(state).create_retriever()


def get_answer_llm(state: dict):
    runtime = get_runtime(state)
    return runtime.with_answer_cache(runtime.create_llm())


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object from an LLM response.

    Providers occasionally wrap "JSON only" responses in markdown fences or a
    short preface. Scanning for a decodable object keeps agent control-flow from
    falling back unnecessarily on harmless formatting drift.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise ValueError("No JSON object found in LLM response")


def parse_query_analysis(text: str, fallback_query: str) -> dict[str, Any]:
    data = parse_json_object(text)
    data.setdefault("rewritten_query", fallback_query)
    return QueryAnalysis.model_validate(data).model_dump()


def parse_retrieval_evaluation(text: str) -> dict[str, Any]:
    return RetrievalEvaluation.model_validate(parse_json_object(text)).model_dump()


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


def split_answer_claims(answer: str) -> list[str]:
    """Split generated prose into simple claim-sized sentences."""
    normalized = " ".join(line.strip("-* \t") for line in answer.splitlines())
    claims = []
    for match in re.finditer(r"[^。！？.!?]+[。！？.!?]?", normalized):
        claim = match.group(0).strip()
        if len(claim) >= 12:
            claims.append(claim)
    return claims


def tokenize_for_support(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", text.lower())
    stopwords = {
        "the", "and", "for", "with", "that", "this", "from", "into", "about",
        "have", "has", "was", "were", "are", "is", "new", "its", "their",
    }
    return {
        token
        for token in tokens
        if token not in stopwords and (len(token) > 2 or "\u4e00" <= token <= "\u9fff")
    }


def score_claim_support(claim: str, source: dict) -> tuple[float, int]:
    claim_tokens = tokenize_for_support(claim)
    if not claim_tokens:
        return 0.0, 0

    source_tokens = tokenize_for_support(
        f"{source.get('title', '')} {source.get('content', '')}"
    )
    overlap = claim_tokens & source_tokens
    return len(overlap) / len(claim_tokens), len(overlap)


def support_level(score: float, overlap_count: int) -> str:
    if score >= 0.6 or overlap_count >= 5:
        return "supported"
    if score >= 0.35 or overlap_count >= 3:
        return "partial"
    return "unsupported"


def bind_claim_citations(answer: str, sources: list[dict], max_sources: int = 2) -> list[dict]:
    """Bind each answer claim to the strongest supporting source indexes."""
    citations = []
    for claim in split_answer_claims(answer):
        scored_sources = []
        for index, source in enumerate(sources, start=1):
            score, overlap_count = score_claim_support(claim, source)
            if score > 0:
                scored_sources.append((score, overlap_count, index))

        scored_sources.sort(key=lambda item: (item[0], item[1]), reverse=True)
        best_score, best_overlap = (scored_sources[0][0], scored_sources[0][1]) if scored_sources else (0.0, 0)
        level = support_level(best_score, best_overlap)
        source_indexes = [
            index
            for score, overlap_count, index in scored_sources[:max_sources]
            if support_level(score, overlap_count) != "unsupported"
        ]

        citations.append({
            "claim": claim,
            "source_indexes": source_indexes,
            "support_level": level if source_indexes else "unsupported",
            "support_score": round(best_score, 3),
        })

    return citations


def assess_retrieval_quality(results: list[dict]) -> dict[str, Any]:
    """Assess hard retrieval quality signals before generation."""
    if not results:
        return {
            "enough_evidence": False,
            "missing_dimensions": ["results"],
            "source_diversity": "low",
            "authority": "unknown",
            "freshness": "unknown",
            "requires_research": True,
        }

    sources = {item.get("source", "unknown") for item in results}
    source_count = len(sources)
    if source_count >= 3:
        diversity = "high"
    elif source_count == 2:
        diversity = "medium"
    else:
        diversity = "low"

    avg_score = sum(float(item.get("score", 0) or 0) for item in results) / len(results)
    authority = "high" if avg_score >= 0.7 else "medium" if avg_score >= 0.45 else "low"

    missing_dimensions = []
    if len(results) < 2:
        missing_dimensions.append("evidence_count")
    if diversity == "low" and len(results) >= 2:
        missing_dimensions.append("source_diversity")
    if authority == "low":
        missing_dimensions.append("authority")

    return {
        "enough_evidence": not missing_dimensions,
        "missing_dimensions": missing_dimensions,
        "source_diversity": diversity,
        "authority": authority,
        "freshness": "unknown",
        "requires_research": bool(missing_dimensions),
    }


def apply_quality_gate(reflection: dict[str, Any], gate: dict[str, Any], query: str) -> dict[str, Any]:
    if gate.get("enough_evidence"):
        return reflection

    gaps = list(dict.fromkeys([*reflection.get("gaps", []), *gate.get("missing_dimensions", [])]))
    action = reflection.get("action", "proceed")
    if action == "proceed":
        action = "expand"

    re_search_query = reflection.get("re_search_query") or f"{query} additional sources"

    return {
        **reflection,
        "gaps": gaps,
        "action": action,
        "re_search_query": re_search_query,
    }


def extract_numeric_values(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", text))


def detect_source_conflicts(results: list[dict]) -> list[dict]:
    """Detect obvious cross-source factual conflicts."""
    conflicts = []
    numeric_by_source = []
    for result in results:
        values = extract_numeric_values(f"{result.get('title', '')} {result.get('content', '')}")
        if values:
            numeric_by_source.append({
                "source": result.get("source", "unknown"),
                "title": result.get("title", ""),
                "values": values,
            })

    for i, left in enumerate(numeric_by_source):
        for right in numeric_by_source[i + 1:]:
            if left["source"] == right["source"]:
                continue
            if left["values"] != right["values"]:
                conflicts.append({
                    "type": "numeric_conflict",
                    "sources": [left["source"], right["source"]],
                    "titles": [left["title"], right["title"]],
                    "values": sorted(left["values"] | right["values"], key=float),
                })
                return conflicts

    return conflicts


def find_unsupported_claims(answer: str, sources: list[dict]) -> list[str]:
    """Flag answer sentences that have weak lexical support in retrieved sources."""
    if not answer or not sources:
        return []

    return [
        citation["claim"]
        for citation in bind_claim_citations(answer, sources)
        if citation["support_level"] == "unsupported"
    ]


async def analyze_query(state: dict) -> dict:
    """用 LLM 分析查询意图、关键词和子查询。"""
    query = state.get("query", "")
    use_history = state.get("use_history", False)
    conversation_history = state.get("conversation_history", [])
    logger.info("analyzing_query", query=query)

    llm = get_llm(state)

    prompt = load_prompt("analyze_query", query=query)

    # 如果启用历史上下文，把历史消息加入 prompt
    if use_history and conversation_history:
        history_lines = []
        for msg in conversation_history[-10:]:  # 最多取最近10条
            role = msg.get("role", "user")
            content = msg.get("content", "")
            history_lines.append(f"{role}: {content}")
        history_context = "\n".join(history_lines)
        prompt = f"历史上下文：\n{history_context}\n\n当前问题：\n{prompt}"

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.chat(messages)
        parsed = parse_query_analysis(response, query)
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

    retriever = get_retriever(state)

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
    results = state.get("retrieval_results", [])
    query = state.get("query", "")

    if not results:
        evaluation = {
            "relevance": "LOW",
            "coverage": 0,
            "action": "proceed",
            "gaps": ["No results"],
            "re_search_query": "",
        }
        quality_gate = assess_retrieval_quality(results)
        return {
            "retrieval_evaluation": evaluation,
            "retrieval_quality_gate": quality_gate,
            "reflection": evaluation,
        }

    llm = get_llm(state)

    context = format_context(results[:5])
    prompt = load_prompt("evaluate_relevance", query=query, context=context)
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.chat(messages)
        reflection = parse_retrieval_evaluation(response)
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

    quality_gate = assess_retrieval_quality(results)
    reflection = parse_retrieval_evaluation(json.dumps(
        apply_quality_gate(reflection, quality_gate, query)
    ))

    logger.info(
        "relevance_evaluated",
        relevance=reflection.get("relevance"),
        coverage=reflection.get("coverage"),
        action=reflection.get("action"),
    )

    return {
        "retrieval_evaluation": reflection,
        "retrieval_quality_gate": quality_gate,
        # Backward-compatible alias for callers that still inspect reflection.
        "reflection": reflection,
    }


async def re_search(state: dict) -> dict:
    """用补充 query 进行额外检索，合并结果。"""
    reflection = state.get("retrieval_evaluation") or state.get("reflection", {})
    re_search_query = reflection.get("re_search_query", "")

    logger.info("re_searching", query=re_search_query)

    if not re_search_query:
        return {"re_search_count": state.get("re_search_count", 0) + 1}

    retriever = get_retriever(state)

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
    """Generate answer using LLM with retrieved context."""
    query = state.get("query", "")
    results = state.get("retrieval_results", [])

    if not results:
        return {"answer": "I couldn't find any relevant articles to answer your question.", "sources": []}

    llm = get_answer_llm(state)

    # Format context and sources
    context = format_context(results)
    sources = format_sources(results)

    # Load prompt template
    prompt = load_prompt("generate_answer", query=query, context=context)

    # Generate answer
    messages = [{"role": "user", "content": prompt}]

    try:
        answer = await llm.chat(messages)
    except Exception as e:
        logger.error("answer_generation_failed", error=str(e))
        return {"answer": f"Failed to generate answer: {e}", "sources": sources}

    return {"answer": answer, "sources": sources}


async def self_reflect(state: dict) -> dict:
    """深度反思：检查答案质量、来源覆盖、是否需要补充。"""
    answer = state.get("answer", "")
    query = state.get("query", "")
    results = state.get("retrieval_results", [])
    sources = state.get("sources", [])

    issues = []

    # 检查答案长度
    if len(answer) < 80:
        issues.append("答案过短")

    # 检查来源覆盖
    if not sources:
        issues.append("无来源引用")
    elif len(sources) < 2:
        issues.append("来源单一")

    # 检查是否有实质性内容
    if not any(c.isalpha() for c in answer):
        issues.append("答案无实质内容")

    # 检查是否直接使用了检索结果（通过关键词匹配）
    has_citation = any(
        keyword in answer.lower()
        for result in results[:3]
        for keyword in (result.get("title", "") or "").split()[:5]
        if len(keyword) > 4
    )
    if not has_citation:
        issues.append("答案未引用检索来源")

    citation_sources = sources or results
    citations = bind_claim_citations(answer, citation_sources)
    unsupported_claims = [
        citation["claim"]
        for citation in citations
        if citation["support_level"] == "unsupported"
    ]
    if unsupported_claims:
        issues.append("存在未被来源支撑的断言")

    # 质量评分
    quality_map = {0: "POOR", 1: "FAIR", 2: "GOOD", 3: "EXCELLENT"}
    num_issues = len(issues)
    quality = quality_map.get(min(num_issues, 3), "POOR")

    return {
        "citations": citations,
        "answer_reflection": {
            "quality": quality,
            "issues": issues,
            "needs_revision": num_issues >= 2,
            "unsupported_claims": unsupported_claims,
        }
    }


async def compare_sources(state: dict) -> dict:
    """多源对比：检查检索结果是否来自不同来源，生成对比摘要。"""
    results = state.get("retrieval_results", [])

    if len(results) < 2:
        return {"source_comparison": None}

    # 按来源分组
    sources: dict[str, list[dict]] = {}
    for r in results:
        src = r.get("source", "unknown")
        if src not in sources:
            sources[src] = []
        sources[src].append(r)

    # 如果来源单一，无需对比
    if len(sources) < 2:
        return {"source_comparison": None}

    comparison = {
        "num_sources": len(sources),
        "sources": list(sources.keys()),
        "consensus": "",  # 共识内容
        "conflicts": detect_source_conflicts(results),  # 矛盾内容
    }

    # 简单逻辑：检查不同来源对同一事件的描述是否一致
    # （MVP 版本不做复杂比对了，只记录来源多样性）

    return {"source_comparison": comparison}


async def generate_answer_stream(state: dict) -> AsyncIterator[str]:
    """流式生成回答，逐 token 产出。

    与 generate_answer() 不同，此函数返回 AsyncIterator[str]，
    用于 SSE 实时流式输出。
    """
    query = state.get("query", "")
    results = state.get("retrieval_results", [])

    if not results:
        yield "I couldn't find any relevant articles to answer your question."
        return

    llm = get_answer_llm(state)

    context = format_context(results)
    prompt = load_prompt("generate_answer", query=query, context=context)
    messages = [{"role": "user", "content": prompt}]

    try:
        async for token in llm.stream_chat(messages):
            yield token
    except Exception as e:
        logger.error("stream_answer_generation_failed", error=str(e))
        yield f"\n\n[Error: {e}]"
