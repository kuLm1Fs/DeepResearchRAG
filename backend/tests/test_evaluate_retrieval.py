import unittest
from unittest.mock import patch

from scripts import evaluate_retrieval as eval_script


class EvaluateRetrievalTests(unittest.IsolatedAsyncioTestCase):
    def test_default_queries_cover_four_categories_with_five_each(self):
        counts = {category: 0 for category in eval_script.CATEGORIES}

        self.assertEqual(len(eval_script.TEST_QUERIES), 20)
        for item in eval_script.TEST_QUERIES:
            self.assertTrue(item["query"])
            self.assertTrue(item["expected_categories"])
            for category in item["expected_categories"]:
                counts[category] += 1

        self.assertEqual(
            counts,
            {
                "Sports": 5,
                "Sci/Tech": 5,
                "Business": 5,
                "World": 5,
            },
        )

    def test_metrics_include_precision_recall_and_ndcg_at_requested_k_values(self):
        categories = ["Business", "Sports", "Business", "World", "Business"]
        expected = ["Business"]

        metrics = eval_script.calculate_metrics(categories, expected, [1, 3, 5])

        self.assertAlmostEqual(metrics[1]["precision"], 1.0)
        self.assertAlmostEqual(metrics[3]["precision"], 2 / 3)
        self.assertAlmostEqual(metrics[5]["recall"], 1.0)
        self.assertGreater(metrics[5]["ndcg"], 0.0)
        self.assertLessEqual(metrics[5]["ndcg"], 1.0)

    async def test_evaluate_semantic_logs_search_errors_and_continues(self):
        queries = [
            {"query": "market earnings", "expected_categories": ["Business"]},
            {"query": "world leaders meet", "expected_categories": ["World"]},
        ]

        async def fake_embed_texts_async(texts):
            return [[0.1], [0.2]]

        class FakeStore:
            def search(self, query_embedding, top_k):
                if query_embedding == [0.1]:
                    raise RuntimeError("search failed")
                return [{"category": "World"}]

        with patch.object(eval_script, "embed_texts_async", fake_embed_texts_async):
            result = await eval_script.evaluate_semantic(FakeStore(), queries, top_k=5)

        self.assertEqual(result["query_results"][0]["error"], "search failed")
        self.assertEqual(result["query_results"][1]["retrieved_categories"], ["World"])
        self.assertAlmostEqual(result["summary"]["metrics"][5]["recall"], 0.5)

    async def test_evaluate_multipath_awaits_retriever_and_summarizes_category_precision(self):
        queries = [
            {"query": "football score", "expected_categories": ["Sports"]},
            {"query": "software update", "expected_categories": ["Sci/Tech"]},
        ]

        class FakeRetriever:
            async def retrieve(self, query, top_k):
                if "football" in query:
                    return [{"category": "Sports"}, {"category": "Business"}]
                return [{"category": "World"}]

        result = await eval_script.evaluate_multipath(FakeRetriever(), queries, top_k=5)

        self.assertEqual(
            result["query_results"][0]["retrieved_categories"],
            ["Sports", "Business"],
        )
        self.assertAlmostEqual(result["summary"]["metrics"][5]["precision"], 0.1)
        self.assertAlmostEqual(
            result["summary"]["category_precision_at_5"]["Sports"],
            0.2,
        )
        self.assertAlmostEqual(
            result["summary"]["category_precision_at_5"]["Sci/Tech"],
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
