"""Tests for Feishu integration: block parser, client, collector."""
import time
from unittest.mock import patch, MagicMock

import pytest

from src.ingestion.feishu_block_parser import blocks_to_text, _extract_text_from_elements, _parse_table


# ─── Block Parser ───────────────────────────────────────────────


class TestBlocksToText:
    """Test blocks_to_text conversion from Feishu Docx blocks to Markdown."""

    def test_empty_blocks(self):
        assert blocks_to_text([]) == ""

    def test_text_block(self):
        blocks = [
            {"block_type": 2, "text": {"elements": [{"text_run": {"content": "Hello world"}}]}}
        ]
        assert blocks_to_text(blocks) == "Hello world"

    def test_heading_levels(self):
        for block_type, level in [(3, 1), (4, 2), (5, 3), (6, 4), (7, 5)]:
            blocks = [
                {"block_type": block_type, f"heading{level}": {"elements": [{"text_run": {"content": f"H{level}"}}]}}
            ]
            result = blocks_to_text(blocks)
            assert result == f"{'#' * level} H{level}"

    def test_bullet_list(self):
        blocks = [
            {"block_type": 12, "bullet": {"elements": [{"text_run": {"content": "item A"}}]}},
            {"block_type": 12, "bullet": {"elements": [{"text_run": {"content": "item B"}}]}},
        ]
        result = blocks_to_text(blocks)
        assert "- item A" in result
        assert "- item B" in result

    def test_ordered_list_counter_resets(self):
        blocks = [
            {"block_type": 13, "ordered": {"elements": [{"text_run": {"content": "first"}}]}},
            {"block_type": 13, "ordered": {"elements": [{"text_run": {"content": "second"}}]}},
            {"block_type": 2, "text": {"elements": [{"text_run": {"content": "break"}}]}},
            {"block_type": 13, "ordered": {"elements": [{"text_run": {"content": "new first"}}]}},
        ]
        result = blocks_to_text(blocks)
        lines = result.split("\n")
        assert lines[0] == "1. first"
        assert lines[1] == "2. second"
        assert lines[3] == "1. new first"

    def test_code_block_with_language(self):
        blocks = [
            {
                "block_type": 14,
                "code": {
                    "elements": [{"text_run": {"content": "print('hi')"}}],
                    "style": {"language": 48},  # 48 = python
                },
            }
        ]
        result = blocks_to_text(blocks)
        assert "```python" in result
        assert "print('hi')" in result
        assert result.endswith("```")

    def test_quote_block(self):
        blocks = [
            {"block_type": 15, "quote": {"elements": [{"text_run": {"content": "quoted text"}}]}}
        ]
        result = blocks_to_text(blocks)
        assert "> quoted text" in result

    def test_todo_done(self):
        blocks = [
            {"block_type": 17, "todo": {"elements": [{"text_run": {"content": "task"}}], "style": {"done": True}}}
        ]
        result = blocks_to_text(blocks)
        assert "- [x] task" in result

    def test_todo_not_done(self):
        blocks = [
            {"block_type": 17, "todo": {"elements": [{"text_run": {"content": "task"}}], "style": {"done": False}}}
        ]
        result = blocks_to_text(blocks)
        assert "- [ ] task" in result

    def test_divider(self):
        blocks = [{"block_type": 22}]
        assert blocks_to_text(blocks) == "---"

    def test_image_placeholder(self):
        blocks = [{"block_type": 27}]
        assert blocks_to_text(blocks) == "[图片]"

    def test_file_placeholder(self):
        blocks = [{"block_type": 23}]
        assert blocks_to_text(blocks) == "[文件]"

    def test_page_block_skipped(self):
        blocks = [{"block_type": 1}]
        assert blocks_to_text(blocks) == ""

    def test_unknown_block_type_skipped(self):
        blocks = [{"block_type": 999}]
        assert blocks_to_text(blocks) == ""


class TestExtractTextFromElements:
    """Test _extract_text_from_elements helper."""

    def test_empty_elements(self):
        assert _extract_text_from_elements([]) == ""

    def test_multiple_text_runs(self):
        elements = [
            {"text_run": {"content": "Hello "}},
            {"text_run": {"content": "world"}},
        ]
        assert _extract_text_from_elements(elements) == "Hello world"

    def test_mention_user(self):
        elements = [{"mention_user": {"user_id": "u123"}}]
        assert _extract_text_from_elements(elements) == "@u123"

    def test_mention_doc(self):
        elements = [{"mention_doc": {"title": "Design Doc"}}]
        assert _extract_text_from_elements(elements) == "[Design Doc]"

    def test_equation(self):
        elements = [{"equation": {"content": "E=mc^2"}}]
        assert _extract_text_from_elements(elements) == "$E=mc^2$"

    def test_mixed_elements(self):
        elements = [
            {"text_run": {"content": "See "}},
            {"mention_doc": {"title": "RFC-001"}},
            {"text_run": {"content": " for details"}},
        ]
        assert _extract_text_from_elements(elements) == "See [RFC-001] for details"


class TestParseTable:
    """Test _parse_table for Feishu table blocks."""

    def test_simple_table(self):
        table_block = {
            "block_type": 31,
            "table": {"property": {"row_size": 2, "column_size": 2}},
            "children": ["cell_00", "cell_01", "cell_10", "cell_11"],
        }
        all_blocks = [
            table_block,
            {"block_id": "cell_00", "children": ["txt_00"]},
            {"block_id": "cell_01", "children": ["txt_01"]},
            {"block_id": "cell_10", "children": ["txt_10"]},
            {"block_id": "cell_11", "children": ["txt_11"]},
            {"block_id": "txt_00", "block_type": 2, "text": {"elements": [{"text_run": {"content": "A"}}]}},
            {"block_id": "txt_01", "block_type": 2, "text": {"elements": [{"text_run": {"content": "B"}}]}},
            {"block_id": "txt_10", "block_type": 2, "text": {"elements": [{"text_run": {"content": "C"}}]}},
            {"block_id": "txt_11", "block_type": 2, "text": {"elements": [{"text_run": {"content": "D"}}]}},
        ]
        result = _parse_table(table_block, all_blocks)
        assert "| A | B |" in result[0]
        assert "| --- | --- |" in result[1]
        assert "| C | D |" in result[2]

    def test_empty_table(self):
        table_block = {"block_type": 31, "table": {"property": {"row_size": 0, "column_size": 0}}}
        assert _parse_table(table_block, []) == []


# ─── Client ─────────────────────────────────────────────────────


class TestRateLimiter:
    """Test _RateLimiter sliding window."""

    def test_allows_within_limit(self):
        from src.ingestion.feishu_client import _RateLimiter
        limiter = _RateLimiter(max_requests=5, window_seconds=1.0)
        for _ in range(5):
            limiter.wait()
        # Should not block — all 5 within window

    def test_blocks_when_window_full(self):
        from src.ingestion.feishu_client import _RateLimiter
        limiter = _RateLimiter(max_requests=2, window_seconds=0.1)
        limiter.wait()
        limiter.wait()
        start = time.monotonic()
        limiter.wait()  # Should sleep ~0.1s
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # some tolerance


class TestFeishuClient:
    """Test FeishuClient token management and API methods."""

    def _make_client(self):
        from src.ingestion.feishu_client import FeishuClient
        return FeishuClient(app_id="test_id", app_secret="test_secret", api_base="https://open.feishu.cn/open-apis")

    @patch("src.ingestion.feishu_client.httpx.Client")
    def test_token_refresh(self, mock_http_cls):
        mock_http = MagicMock()
        mock_http_cls.return_value = mock_http

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"code": 0, "tenant_access_token": "t-abc123", "expire": 7200}
        token_resp.raise_for_status = MagicMock()
        mock_http.post.return_value = token_resp

        client = self._make_client()
        token = client._ensure_token()
        assert token == "t-abc123"
        mock_http.post.assert_called_once()

    @patch("src.ingestion.feishu_client.httpx.Client")
    def test_token_cached(self, mock_http_cls):
        mock_http = MagicMock()
        mock_http_cls.return_value = mock_http

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"code": 0, "tenant_access_token": "t-abc", "expire": 7200}
        token_resp.raise_for_status = MagicMock()
        mock_http.post.return_value = token_resp

        client = self._make_client()
        client._ensure_token()
        client._ensure_token()
        # Should only call auth endpoint once (second call uses cache)
        assert mock_http.post.call_count == 1

    @patch("src.ingestion.feishu_client.httpx.Client")
    def test_list_spaces(self, mock_http_cls):
        mock_http = MagicMock()
        mock_http_cls.return_value = mock_http

        # Token response
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"code": 0, "tenant_access_token": "t-abc", "expire": 7200}
        token_resp.raise_for_status = MagicMock()

        # Spaces response
        spaces_resp = MagicMock()
        spaces_resp.status_code = 200
        spaces_resp.json.return_value = {
            "code": 0,
            "data": {
                "items": [{"space_id": "s1", "name": "Engineering"}],
                "has_more": False,
            },
        }
        spaces_resp.raise_for_status = MagicMock()

        mock_http.post.return_value = token_resp
        mock_http.get.return_value = spaces_resp

        client = self._make_client()
        spaces = client.list_spaces()
        assert len(spaces) == 1
        assert spaces[0]["space_id"] == "s1"

    @patch("src.ingestion.feishu_client.httpx.Client")
    def test_context_manager(self, mock_http_cls):
        mock_http = MagicMock()
        mock_http_cls.return_value = mock_http

        from src.ingestion.feishu_client import FeishuClient
        with FeishuClient("id", "secret", "https://open.feishu.cn/open-apis") as client:
            assert client is not None
        mock_http.close.assert_called_once()


# ─── Collector ──────────────────────────────────────────────────


class TestFeishuCollector:
    """Test FeishuCollector article normalization and pipeline registration."""

    def test_inherits_base(self):
        from src.ingestion.feishu_collector import FeishuCollector
        from src.ingestion.base import BaseCollector
        assert issubclass(FeishuCollector, BaseCollector)

    def test_name_is_feishu(self):
        from src.ingestion.feishu_collector import FeishuCollector
        collector = FeishuCollector()
        assert collector.name == "feishu"

    def test_close_without_client(self):
        from src.ingestion.feishu_collector import FeishuCollector
        collector = FeishuCollector()
        collector.close()  # Should not raise

    @patch("src.ingestion.feishu_collector.FeishuCollector._get_client")
    def test_process_node_builds_article(self, mock_get_client):
        from src.ingestion.feishu_collector import FeishuCollector

        mock_client = MagicMock()
        mock_client.get_document_blocks.return_value = [
            {"block_type": 2, "text": {"elements": [{"text_run": {"content": "Test content"}}]}}
        ]
        mock_get_client.return_value = mock_client

        collector = FeishuCollector()
        node = {"title": "Doc Title", "obj_token": "obj_123", "node_token": "node_456"}
        article = collector._process_node(mock_client, node, "EngSpace", "space_1")

        assert article is not None
        assert article["title"] == "Doc Title"
        assert article["source"] == "Feishu:EngSpace"
        assert article["language"] == "zh"
        assert article["category"] == "wiki"
        assert "content_hash" in article
        assert article["feishu_space_id"] == "space_1"
        assert article["feishu_node_token"] == "node_456"
        assert article["feishu_obj_token"] == "obj_123"

    @patch("src.ingestion.feishu_collector.FeishuCollector._get_client")
    def test_process_node_returns_none_for_empty_doc(self, mock_get_client):
        from src.ingestion.feishu_collector import FeishuCollector

        mock_client = MagicMock()
        mock_client.get_document_blocks.return_value = []
        mock_get_client.return_value = mock_client

        collector = FeishuCollector()
        node = {"title": "Empty", "obj_token": "obj_000", "node_token": "node_000"}
        result = collector._process_node(mock_client, node, "Space", "s1")
        assert result is None

    @patch("src.ingestion.feishu_collector.FeishuCollector._get_client")
    def test_process_node_returns_none_for_no_obj_token(self, mock_get_client):
        from src.ingestion.feishu_collector import FeishuCollector

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        collector = FeishuCollector()
        node = {"title": "No Token", "obj_token": "", "node_token": "node_xxx"}
        result = collector._process_node(mock_client, node, "Space", "s1")
        assert result is None


class TestFeishuPipelineRegistration:
    """Test that FeishuCollector is conditionally registered based on config."""

    @staticmethod
    def _patch_feishu_credentials(app_id: str, app_secret: str):
        """Patch feishu credentials on both settings singletons.

        src.core.config.settings and core.config.settings are different
        objects due to sys.path manipulation. Pipeline uses core.config,
        tests use src.core.config — both must be patched.
        """
        from src.core.config import settings as s1
        from core.config import settings as s2
        old = (s1.feishu_app_id, s1.feishu_app_secret, s2.feishu_app_id, s2.feishu_app_secret)
        s1.feishu_app_id = s2.feishu_app_id = app_id
        s1.feishu_app_secret = s2.feishu_app_secret = app_secret
        return old

    @staticmethod
    def _restore_feishu_credentials(old):
        from src.core.config import settings as s1
        from core.config import settings as s2
        s1.feishu_app_id, s1.feishu_app_secret, s2.feishu_app_id, s2.feishu_app_secret = old

    def test_registered_when_credentials_set(self):
        old = self._patch_feishu_credentials("test_app_id", "test_secret")
        try:
            from src.ingestion.pipeline import IngestionPipeline
            pipeline = IngestionPipeline()
            pipeline.register_defaults()
            assert "feishu" in pipeline.list_collectors()
        finally:
            self._restore_feishu_credentials(old)

    def test_not_registered_when_credentials_empty(self):
        old = self._patch_feishu_credentials("", "")
        try:
            from src.ingestion.pipeline import IngestionPipeline
            pipeline = IngestionPipeline()
            pipeline.register_defaults()
            assert "feishu" not in pipeline.list_collectors()
        finally:
            self._restore_feishu_credentials(old)
