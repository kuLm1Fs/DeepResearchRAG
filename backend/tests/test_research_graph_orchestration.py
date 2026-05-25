import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent import research_graph


class ResearchGraphOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_top_level_agent_package_imports(self):
        import agent

        self.assertTrue(hasattr(agent, "run_agent"))
        self.assertTrue(hasattr(agent, "run_research"))

    async def test_planner_node_promotes_sub_questions_to_state(self):
        async def fake_aplanner(query, user_id=None):
            return {
                "data": {
                    "goals": ["understand market"],
                    "sub_questions": ["market size", "adoption risks"],
                }
            }

        with patch.object(research_graph, "aplanner", fake_aplanner):
            result = await research_graph._planner_node({"query": "AI market", "user_id": "u1"})

        self.assertEqual(result["plan"]["goals"], ["understand market"])
        self.assertEqual(result["sub_questions"], ["market size", "adoption risks"])

    async def test_checker_node_calls_checker_once_and_exports_gaps(self):
        calls = []

        async def fake_achecker(claims, evidence):
            calls.append((claims, evidence))
            return {"data": {"coverage": 0.6, "gaps": ["missing competitor evidence"]}}

        state = {
            "analysis": {"claims": [{"claim": "A"}]},
            "evidence": [{"title": "source"}],
        }

        with patch.object(research_graph, "achecker", fake_achecker):
            result = await research_graph._checker_node(state)

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["check_result"]["gaps"], ["missing competitor evidence"])
        self.assertEqual(result["gaps"], ["missing competitor evidence"])

    async def test_retriever_uses_checker_gaps_for_supplemental_search_and_merges_evidence(self):
        seen_queries = []

        def fake_retriever(sub_questions, user_id=None):
            seen_queries.extend(sub_questions)
            return {
                "data": {
                    "evidence": [
                        {"title": "Existing", "content": "same"},
                        {"title": "New", "content": "new evidence"},
                    ]
                }
            }

        state = {
            "query": "AI market",
            "user_id": "u1",
            "sub_questions": ["initial question"],
            "gaps": ["missing adoption data"],
            "evidence": [{"title": "Existing", "content": "same"}],
            "tool_call_count": 1,
        }

        with patch.object(research_graph, "retriever", fake_retriever):
            result = research_graph._call_retriever(state)

        self.assertEqual(seen_queries, ["missing adoption data"])
        self.assertEqual([item["title"] for item in result["evidence"]], ["Existing", "New"])
        self.assertEqual(result["tool_call_count"], 2)

    async def test_should_continue_stops_on_configuration_gaps(self):
        state = {
            "check_result": {"coverage": 0.5, "gaps": ["需要配置 LLM API key 以获得真实核查"]},
            "tool_call_count": 1,
            "max_tool_calls": 20,
        }

        self.assertEqual(research_graph.should_continue(state), "writer")

    async def test_nodes_notify_step_progress(self):
        seen_steps = []

        async def on_step(step, state):
            seen_steps.append((step, state.get("query")))

        async def fake_aplanner(query, user_id=None):
            return {"data": {"sub_questions": ["q1"]}}

        with patch.object(research_graph, "aplanner", fake_aplanner):
            result = await research_graph._planner_node({
                "query": "AI market",
                "user_id": "u1",
                "on_step": on_step,
            })

        self.assertEqual(result["current_step"], "planner")
        self.assertEqual(seen_steps, [("planner", "AI market")])


if __name__ == "__main__":
    unittest.main()
