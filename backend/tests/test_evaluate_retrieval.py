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

    def test_source_recall_scores_finance_expected_sources(self):
        results = [
            {"doc_name": "AAPL_2023_10K", "title": "Apple 2023 Form 10-K"},
            {"source_id": "MSFT_2023_10K", "title": "Microsoft 2023 Form 10-K"},
            {"url": "https://example.com/NVDA_2024_10K"},
        ]

        self.assertAlmostEqual(
            eval_script.source_recall_at_k(
                results,
                ["AAPL_2023_10K", "NVDA_2024_10K"],
                3,
            ),
            1.0,
        )
        self.assertAlmostEqual(
            eval_script.source_recall_at_k(
                results,
                ["AAPL_2023_10K", "NVDA_2024_10K"],
                2,
            ),
            0.5,
        )

    def test_badcase_summary_and_quality_gate_fail_on_regression(self):
        query_results = [
            {
                "id": "bc-001",
                "query": "Compare Apple and Microsoft revenue",
                "is_badcase": True,
                "expected_sources": ["AAPL_2023_10K", "MSFT_2023_10K"],
                "source_recall_at_5": 0.5,
                "metrics": eval_script.calculate_metrics(["Business"] * 5, ["Business"]),
            },
            {
                "id": "gold-001",
                "query": "Apple revenue",
                "expected_sources": ["AAPL_2023_10K"],
                "source_recall_at_5": 1.0,
                "metrics": eval_script.calculate_metrics(["Business"] * 5, ["Business"]),
            },
        ]

        summary = eval_script.summarize_results(query_results, [10.0, 20.0])

        self.assertEqual(summary["source_recall_at_5"], 0.75)
        self.assertEqual(summary["badcase_regression"]["total"], 1)
        self.assertEqual(summary["badcase_regression"]["fixed"], 0)
        self.assertEqual(summary["badcase_regression"]["failed_ids"], ["bc-001"])
        self.assertFalse(eval_script.quality_gate_passed(summary))

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
            {
                "id": "gold-001",
                "query": "football score",
                "expected_categories": ["Sports"],
                "expected_sources": ["sports-source-1"],
            },
            {"query": "software update", "expected_categories": ["Sci/Tech"]},
        ]

        class FakeRetriever:
            async def retrieve(self, query, top_k):
                if "football" in query:
                    return [
                        {"category": "Sports", "source_id": "sports-source-1"},
                        {"category": "Business"},
                    ]
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
        self.assertAlmostEqual(result["query_results"][0]["source_recall_at_5"], 1.0)


if __name__ == "__main__":
    unittest.main()
