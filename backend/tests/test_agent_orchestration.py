import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from src.agent import graph as agent_graph
from src.agent import nodes


class AgentJsonParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_query_accepts_fenced_json_from_llm(self):
        class FakeLLM:
            async def chat(self, messages):
                return """```json
{
  "intent": "analysis",
  "rewritten_query": "AI regulation news",
  "sub_queries": ["US AI regulation", "EU AI Act"],
  "keywords": ["AI", "regulation"]
}
```"""

        with (
            patch("llm.create_llm", return_value=FakeLLM()),
            patch.object(nodes, "load_prompt", return_value="prompt"),
        ):
            result = await nodes.analyze_query({"query": "what is happening with AI rules?"})

        self.assertEqual(result["parsed_query"]["intent"], "analysis")
        self.assertEqual(
            result["search_queries"],
            ["AI regulation news", "US AI regulation", "EU AI Act"],
        )

    async def test_evaluate_relevance_stores_retrieval_evaluation_separately(self):
        class FakeLLM:
            async def chat(self, messages):
                return """Here is the evaluation:
{
  "relevance": "LOW",
  "coverage": 20,
  "gaps": ["latest policy reaction"],
  "action": "re_search",
  "re_search_query": "latest AI policy reaction"
}
"""

        state = {
            "query": "AI policy reaction",
            "retrieval_results": [{"title": "AI policy", "content": "old", "source": "wire"}],
        }

        with (
            patch("llm.create_llm", return_value=FakeLLM()),
            patch.object(nodes, "load_prompt", return_value="prompt"),
        ):
            result = await nodes.evaluate_relevance(state)

        self.assertEqual(result["retrieval_evaluation"]["action"], "re_search")
        self.assertEqual(result["retrieval_evaluation"]["coverage"], 20)
        self.assertNotIn("answer_reflection", result)


class AgentStreamOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_uses_same_retrieval_evaluation_and_research_loop_before_answering(self):
        calls = []
        evaluations = [
            {
                "relevance": "LOW",
                "coverage": 30,
                "gaps": ["second source"],
                "action": "re_search",
                "re_search_query": "expanded policy coverage",
            },
            {
                "relevance": "HIGH",
                "coverage": 90,
                "gaps": [],
                "action": "proceed",
                "re_search_query": "",
            },
        ]

        async def fake_analyze(state):
            calls.append("analyze")
            return {"parsed_query": {"intent": "analysis"}, "search_queries": ["ai policy"]}

        async def fake_plan(state):
            calls.append("plan")
            return {"search_plan": {"queries": ["ai policy"], "per_query": 1, "total": 2}}

        async def fake_retrieve(state):
            calls.append("retrieve")
            return {
                "retrieval_results": [
                    {"title": "A", "content": "one", "source": "s1", "category": "World", "score": 0.7}
                ],
                "filtered_results": [],
            }

        async def fake_evaluate(state):
            calls.append("evaluate")
            evaluation = evaluations.pop(0)
            return {"retrieval_evaluation": evaluation}

        async def fake_re_search(state):
            calls.append("re_search")
            return {
                "retrieval_results": [
                    {"title": "A", "content": "one", "source": "s1", "category": "World", "score": 0.7},
                    {"title": "B", "content": "two", "source": "s2", "category": "World", "score": 0.6},
                ],
                "filtered_results": [],
                "re_search_count": 1,
            }

        async def fake_compare(state):
            calls.append("compare")
            return {"source_comparison": {"num_sources": 2, "sources": ["s1", "s2"], "conflicts": []}}

        async def fake_stream(state):
            calls.append("answer_stream")
            yield "done"

        with (
            patch.object(agent_graph, "analyze_query", fake_analyze),
            patch.object(agent_graph, "plan_retrieval", fake_plan),
            patch.object(agent_graph, "retrieve", fake_retrieve),
            patch.object(agent_graph, "evaluate_relevance", fake_evaluate),
            patch.object(agent_graph, "re_search", fake_re_search),
            patch.object(agent_graph, "compare_sources", fake_compare),
            patch.object(agent_graph, "generate_answer_stream", fake_stream),
        ):
            events = [
                event
                async for event in agent_graph.run_agent_stream("AI policy", trace_id="t1", top_k=2)
            ]

        self.assertEqual(
            calls,
            ["analyze", "plan", "retrieve", "evaluate", "re_search", "evaluate", "compare", "answer_stream"],
        )
        self.assertEqual(events[0]["type"], "sources")
        self.assertEqual(len(events[0]["data"]), 2)
        self.assertEqual(events[-1]["data"]["answer"], "done")
        self.assertEqual(events[-1]["data"]["trace_id"], "t1")


if __name__ == "__main__":
    unittest.main()
