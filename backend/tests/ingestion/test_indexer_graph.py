"""Tests for indexer.py's graph build hook (Phase 2 of GraphRAG).

The contract being tested:
  - When build_graph=True and graph_enabled=True, index_articles() calls
    build_graph_for_articles() after the Milvus insert succeeds.
  - When the graph build raises, the vector path is NOT rolled back; the
    error is captured in stats["graph_errors"] and the function returns.
  - When build_graph=False, the graph layer is never invoked.
  - When graph_enabled=False (settings), the graph layer is never invoked.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sys

# Pre-load the top-level ``graph.builder`` so the indexer's lazy import
# (``from graph.builder import build_graph_for_articles``) succeeds even
# after another test module has loaded the same file as ``src.graph.builder``.
# Without this, when ``tests/graph/`` runs first the lazy import inside
# index_articles() can raise ModuleNotFoundError because Python's import
# system finds ``src.graph.builder`` already in sys.modules and doesn't
# bind a separate ``graph.builder`` key — the indexer's
# ``from graph.builder import ...`` then fails.
try:
    import graph.builder  # noqa: F401
    _GRAPH_BUILDER_MOD_NAME = "graph.builder"
except ImportError:
    # ``src.graph.builder`` is the only spelling available; use it instead.
    import src.graph.builder  # noqa: F401
    _GRAPH_BUILDER_MOD_NAME = "src.graph.builder"


def _graph_builder_module():
    """Return the graph.builder module object from sys.modules."""
    return sys.modules[_GRAPH_BUILDER_MOD_NAME]


# After the try/except, ensure both module names point to the same object.
# In some test orders Python leaves only ``src.graph.builder`` in
# sys.modules; the indexer's lazy ``from graph.builder import ...`` then
# fails. We force a real top-level ``graph.builder`` key so the lazy
# import inside index_articles() succeeds.
if "src.graph.builder" in sys.modules and "graph.builder" not in sys.modules:
    # Re-bind via the top-level import so sys.modules['graph.builder'] exists.
    # This is safe: both keys point to the same .py file.
    sys.modules["graph.builder"] = sys.modules["src.graph.builder"]


def _article(content_hash: str = "h1", title: str = "T1", content: str = "Some content.") -> dict:
    return {
        "content_hash": content_hash,
        "title": title,
        "pub_time": "2026-01-01",
        "source": "Test",
        "lead": "",
        "content": content,
        "language": "en",
        "category": "news",
        "published_at": 0,
        "url": "https://example.com",
        "external_id": "ext1",
    }


def _mock_milvus():
    store = MagicMock()
    store.insert = MagicMock(return_value=[1, 2, 3])
    return store


def _fake_graph_stats(entities: int = 5, relations: int = 3, errors: int = 0) -> dict:
    return {
        "articles_in": 1,
        "articles_skipped": 0,
        "chunks_processed": 2,
        "entities_upserted": entities,
        "relations_upserted": relations,
        "errors": errors,
    }


def _patched_embed():
    """Mock the embedding function (avoid hitting the real API in tests).

    Patches the *bound name* in the indexer's module namespace. The indexer
    does ``from vectorstore import embed_texts_async``, so the name
    ``embed_texts_async`` lives in ``src.ingestion.indexer`` and that's
    the lookup site we need to patch.
    """
    return patch(
        "src.ingestion.indexer.embed_texts_async",
        new=AsyncMock(return_value=[[0.1] * 1024] * 3),
    )


def _patched_graph_build(side_effect=None, return_value=None):
    """Mock the graph build function (avoid hitting Neo4j in tests).

    The indexer does ``from graph.builder import build_graph_for_articles``
    lazily inside ``index_articles()`` — it's *not* bound at module import
    time, so we must patch the source module.

    We resolve to whichever name is currently in ``sys.modules`` (test
    isolation may leave it as either ``graph.builder`` or
    ``src.graph.builder``). Both point to the same ``.py`` file, so
    patching either attribute works: the indexer's lazy import rebinds
    to the mock on the next call.
    """
    if side_effect is not None:
        replacement = AsyncMock(side_effect=side_effect)
    else:
        replacement = AsyncMock(return_value=return_value or _fake_graph_stats())
    if "graph.builder" in sys.modules:
        target_mod = sys.modules["graph.builder"]
    else:
        target_mod = sys.modules["src.graph.builder"]
    return patch.object(target_mod, "build_graph_for_articles", replacement)


class TestIndexerGraphHook:
    @pytest.mark.asyncio
    async def test_calls_graph_build_when_enabled(self):
        """build_graph=True + graph_enabled=True → calls build_graph_for_articles"""
        from src.ingestion.indexer import index_articles

        with _patched_embed(), _patched_graph_build(return_value=_fake_graph_stats(2, 1)) as mock_build:
            stats = await index_articles(
                articles=[_article()],
                store=_mock_milvus(),
                build_graph=True,
            )
        mock_build.assert_awaited_once()
        assert stats["graph_entities"] == 2
        assert stats["graph_relations"] == 1
        assert stats["graph_errors"] == 0

    @pytest.mark.asyncio
    async def test_graph_build_failure_does_not_rollback_vector(self):
        """Vector insert is the source of truth — graph errors are isolated."""
        from src.ingestion.indexer import index_articles

        milvus = _mock_milvus()
        with _patched_embed(), _patched_graph_build(side_effect=RuntimeError("Neo4j down")):
            stats = await index_articles(
                articles=[_article()],
                store=milvus,
                build_graph=True,
            )

        # Vector insert happened
        milvus.insert.assert_called_once()
        assert stats["inserted"] == 3
        # Graph error was captured, not raised
        assert stats["graph_errors"] == 1
        assert stats["graph_entities"] == 0
        assert stats["graph_relations"] == 0

    @pytest.mark.asyncio
    async def test_skips_graph_when_build_graph_false(self):
        """build_graph=False → graph build is not called."""
        from src.ingestion.indexer import index_articles

        with _patched_embed(), _patched_graph_build() as mock_build:
            stats = await index_articles(
                articles=[_article()],
                store=_mock_milvus(),
                build_graph=False,
            )
        mock_build.assert_not_awaited()
        assert stats["graph_entities"] == 0
        assert stats["graph_relations"] == 0
        assert stats["graph_errors"] == 0

    @pytest.mark.asyncio
    async def test_skips_graph_when_disabled_in_settings(self):
        """settings.graph_enabled=False → graph build is not called."""
        from src.ingestion import indexer as indexer_mod
        from src.ingestion.indexer import index_articles

        with _patched_embed(), patch.object(
            indexer_mod, "settings"
        ) as mock_settings, _patched_graph_build() as mock_build:
            mock_settings.graph_enabled = False
            stats = await index_articles(
                articles=[_article()],
                store=_mock_milvus(),
                build_graph=True,  # caller asked, but settings veto
            )
        mock_build.assert_not_awaited()
        assert stats["graph_entities"] == 0

    @pytest.mark.asyncio
    async def test_skips_graph_when_no_articles(self):
        """Empty articles list → graph build is not called (no work to do)."""
        from src.ingestion.indexer import index_articles

        with _patched_graph_build() as mock_build:
            stats = await index_articles(
                articles=[],
                store=_mock_milvus(),
                build_graph=True,
            )
        mock_build.assert_not_awaited()
        assert stats["articles"] == 0
        assert stats["chunks"] == 0

    @pytest.mark.asyncio
    async def test_graph_stats_flow_through(self):
        """When graph build succeeds, its counts land in stats."""
        from src.ingestion.indexer import index_articles

        with _patched_embed(), _patched_graph_build(
            return_value=_fake_graph_stats(entities=7, relations=4)
        ):
            stats = await index_articles(
                articles=[_article()],
                store=_mock_milvus(),
                build_graph=True,
            )
        assert stats["graph_entities"] == 7
        assert stats["graph_relations"] == 4
        assert stats["graph_errors"] == 0

    @pytest.mark.asyncio
    async def test_default_build_graph_is_true(self):
        """Caller can omit build_graph and still trigger graph build."""
        from src.ingestion.indexer import index_articles

        with _patched_embed(), _patched_graph_build(
            return_value=_fake_graph_stats(entities=2, relations=1)
        ) as mock_build:
            stats = await index_articles(
                articles=[_article()],
                store=_mock_milvus(),
                # No build_graph arg — should default to True
            )
        mock_build.assert_awaited_once()
        assert stats["graph_entities"] == 2
        assert stats["graph_relations"] == 1

    @pytest.mark.asyncio
    async def test_passed_in_stats_keys_present(self):
        """All four graph stat keys (entities/relations/skipped/errors) are in stats."""
        from src.ingestion.indexer import index_articles

        with _patched_embed(), _patched_graph_build():
            stats = await index_articles(
                articles=[_article()],
                store=_mock_milvus(),
                build_graph=True,
            )
        # All graph stat keys must be present, even when default 0
        for key in ("graph_entities", "graph_relations", "graph_errors"):
            assert key in stats
            assert isinstance(stats[key], int)
