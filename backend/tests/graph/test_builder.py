"""Unit tests for graph.builder (Neo4j + embedding are mocked)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.graph.builder import _dedupe_entities, build_graph_for_articles
from src.graph.schema import Entity, Relation


def _article(content_hash: str = "hash1", title: str = "Test") -> dict:
    return {
        "content_hash": content_hash,
        "title": title,
        "pub_time": "2026-01-01",
        "source": "TestSource",
        "lead": "",
        "content": "Apple Inc. announced Q3 earnings. Tim Cook is the CEO.",
        "language": "en",
        "category": "news",
        "published_at": 1735689600,
        "url": "https://example.com/test",
        "external_id": "ext1",
    }


def _mock_extractor_with_entities(entities: list[Entity], relations: list[Relation]):
    """Build a mock extractor that returns canned data for any chunk."""
    ext = MagicMock()
    ext.extract_for_chunks = AsyncMock(return_value=[
        (entities, relations) for _ in range(10)  # return same for any chunk
    ])
    ext.close = AsyncMock()
    return ext


def _mock_store():
    store = MagicMock()
    store._get_driver = AsyncMock()
    store.init_indexes = AsyncMock()
    store.upsert_document = AsyncMock()
    store.upsert_entities = AsyncMock(return_value=2)
    store.upsert_relations = AsyncMock(return_value=1)
    store.link_entity_to_chunk = AsyncMock()
    store.close = AsyncMock()
    return store


class TestDedupeEntities:
    def test_collapses_same_entity_id(self):
        e1 = Entity(
            entity_id="苹果:Company", name="苹果", type="Company",
            description="short desc", source_chunk_ids=["c1"]
        )
        e2 = Entity(
            entity_id="苹果:Company", name="苹果", type="Company",
            description="longer description of Apple Inc Cupertino iPhone maker.",
            source_chunk_ids=["c2"]
        )
        unique = _dedupe_entities([e1, e2])
        assert len(unique) == 1
        merged = unique[0]
        # Longer description wins
        assert "longer" in merged.description
        # mention_count is 2 (one per extraction)
        assert merged.mention_count == 2
        # chunk ids merged
        assert set(merged.source_chunk_ids) == {"c1", "c2"}

    def test_keeps_distinct_entities_separate(self):
        e1 = Entity(
            entity_id="苹果:Company", name="苹果", type="Company",
            description="long enough description for apple.",
            source_chunk_ids=["c1"]
        )
        e2 = Entity(
            entity_id="微软:Company", name="微软", type="Company",
            description="long enough description for microsoft.",
            source_chunk_ids=["c1"]
        )
        unique = _dedupe_entities([e1, e2])
        assert len(unique) == 2


class TestBuildGraphForArticles:
    @pytest.mark.asyncio
    async def test_empty_articles(self):
        stats = await build_graph_for_articles(
            articles=[],
            store=_mock_store(),
            extractor=_mock_extractor_with_entities([], []),
        )
        assert stats["articles_in"] == 0
        assert stats["chunks_processed"] == 0

    @pytest.mark.asyncio
    async def test_skips_when_graph_disabled(self):
        with patch("src.graph.builder.settings") as s:
            s.graph_enabled = False
            s.data_dir = MagicMock()
            stats = await build_graph_for_articles(
                articles=[_article()],
                store=_mock_store(),
                extractor=_mock_extractor_with_entities([], []),
            )
        assert stats["articles_in"] == 1
        # Nothing was processed
        assert stats["chunks_processed"] == 0

    @pytest.mark.asyncio
    async def test_end_to_end(self, tmp_path):
        from src.graph import builder as builder_mod

        # Use a fresh tmp ledger so we don't see content from a prior test
        fresh_ledger = tmp_path / "graph_processed.json"

        entities = [
            Entity(
                entity_id="苹果:Company", name="苹果", type="Company",
                description="long enough description for apple.",
                source_chunk_ids=["c1"]
            ),
            Entity(
                entity_id="tim cook:Person", name="tim cook", type="Person",
                description="long enough description for tim cook.",
                source_chunk_ids=["c1"]
            ),
        ]
        relations = [
            Relation(
                source="苹果", target="tim cook", type="led_by",
                description="Apple is led by Tim Cook since 2011.",
                keywords=["ceo"], weight=0.9,
                source_chunk_ids=["c1"]
            )
        ]
        extractor = _mock_extractor_with_entities(entities, relations)
        store = _mock_store()

        # Mock the embedding call and use a fresh ledger
        with patch.object(builder_mod, "_LEDGER_PATH", fresh_ledger), \
             patch("src.graph.builder.embed_texts_async", new=AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])):
            stats = await build_graph_for_articles(
                articles=[_article()],
                store=store,
                extractor=extractor,
            )

        assert stats["articles_in"] == 1
        # We should have at least 1 chunk
        assert stats["chunks_processed"] >= 1
        # Entities and relations upserted
        assert stats["entities_upserted"] == 2
        assert stats["relations_upserted"] == 1
        # Store methods were called (init_indexes/close are only called when
        # the builder owns the store; when caller passes one in, we trust them)
        store.upsert_entities.assert_awaited_once()
        store.upsert_relations.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_already_processed(self, tmp_path):
        from src.graph import builder as builder_mod

        # Pre-populate the ledger
        ledger_path = tmp_path / "graph_processed.json"
        ledger_path.write_text(json.dumps(["hash1"]))
        with patch.object(builder_mod, "_LEDGER_PATH", ledger_path):
            store = _mock_store()
            extractor = _mock_extractor_with_entities([], [])

            with patch("src.graph.builder.embed_texts_async", new=AsyncMock(return_value=[])):
                stats = await build_graph_for_articles(
                    articles=[_article(content_hash="hash1")],
                    store=store,
                    extractor=extractor,
                )

        assert stats["articles_skipped"] == 1
        assert stats["chunks_processed"] == 0
        # Extractor should not have been called
        extractor.extract_for_chunks.assert_not_awaited()
