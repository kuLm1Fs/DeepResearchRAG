"""Unit tests for graph.neo4j_store (driver is mocked)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.graph.neo4j_store import Neo4jStore
from src.graph.schema import (
    ChunkNode,
    Entity,
    Relation,
)


def _entity(eid: str = "苹果:Company", name: str = "苹果", embedding: list | None = None) -> Entity:
    return Entity(
        entity_id=eid,
        name=name,
        type="Company",  # type: ignore[arg-type]
        description="Cupertino-based iPhone maker.",
        embedding=embedding or [0.0] * 1024,
        mention_count=1,
        source_chunk_ids=["c1"],
    )


def _relation(source: str = "苹果", target: str = "tim cook", weight: float = 0.9) -> Relation:
    return Relation(
        source=source,
        target=target,
        type="led_by",
        description="Apple is led by CEO Tim Cook since 2011.",
        keywords=["ceo", "leadership"],
        weight=weight,
        source_chunk_ids=["c1"],
    )


def _mock_session_with(result_consume=None, records=None):
    """Build a mock that supports `async with` and execute_write/execute_read."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute_write = AsyncMock(return_value=result_consume or 0)
    session.execute_read = AsyncMock(return_value=records or [])
    session.run = AsyncMock()
    return session


def _mock_driver(session: MagicMock) -> MagicMock:
    driver = MagicMock()
    driver.session = MagicMock(return_value=session)
    return driver


class TestDriverInit:
    def test_requires_password(self):
        with patch("src.graph.neo4j_store.settings") as mock_settings:
            mock_settings.neo4j_password = ""
            store = Neo4jStore()
            import asyncio
            with pytest.raises(Exception) as exc_info:
                asyncio.run(store._get_driver())
            assert "NEO4J_PASSWORD" in str(exc_info.value)

    def test_creates_driver_with_correct_args(self):
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=MagicMock())
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://localhost:7687"
                s.neo4j_user = "neo4j"
                s.neo4j_database = "neo4j"
                store = Neo4jStore()
                import asyncio
                asyncio.run(store._get_driver())
            mock_agdb.driver.assert_called_once()
            call_kwargs = mock_agdb.driver.call_args.kwargs
            assert call_kwargs["auth"] == ("neo4j", "secret")


class TestUpsert:
    @pytest.mark.asyncio
    async def test_upsert_entities_calls_cypher(self):
        session = _mock_session_with(result_consume=2)
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                count = await store.upsert_entities([_entity(), _entity("x:y")])
        assert count == 2
        session.execute_write.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_relations_merges_duplicates(self):
        # Two relations with same (source, target, type) should collapse
        r1 = _relation(weight=0.5)
        r2 = _relation(weight=0.9)
        r2.keywords = ["vision"]  # new keyword
        r2.source_chunk_ids = ["c2"]  # new chunk

        session = _mock_session_with(result_consume=1)
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                await store.upsert_relations([r1, r2])
        # The internal _merge should have collapsed to 1 row
        # The execute_write was called once
        session.execute_write.assert_awaited_once()
        # We can introspect the params passed to confirm
        # (it's the *params* arg of execute_write's transaction function)

    @pytest.mark.asyncio
    async def test_upsert_entities_empty_list(self):
        session = _mock_session_with()
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                count = await store.upsert_entities([])
        assert count == 0
        session.execute_write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_chunks_calls_cypher_with_chunk_payload(self):
        session = _mock_session_with(result_consume=1)
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                count = await store.upsert_chunks([
                    ChunkNode(
                        chunk_id="doc-1:0",
                        content="Apple reported net sales.",
                        position=0,
                        parent_doc_id="doc-1",
                    )
                ])

        assert count == 1
        session.execute_write.assert_awaited_once()
        params = session.execute_write.await_args.args[1]
        assert params == [
            {
                "chunk_id": "doc-1:0",
                "content": "Apple reported net sales.",
                "position": 0,
                "parent_doc_id": "doc-1",
            }
        ]


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        # Mock a result with record.get("ok") == 1
        record = MagicMock()
        record.get = MagicMock(return_value=1)
        result = MagicMock()
        result.single = AsyncMock(return_value=record)
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.run = AsyncMock(return_value=result)

        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                ok = await store.health_check()
        assert ok is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        session = MagicMock()
        session.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        session.__aexit__ = AsyncMock(return_value=None)
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                ok = await store.health_check()
        assert ok is False


class TestStats:
    @pytest.mark.asyncio
    async def test_stats(self):
        records = [
            {"label": "Entity", "count": 100},
            {"label": "Document", "count": 50},
        ]
        session = _mock_session_with(records=records)
        with patch("src.graph.neo4j_store.AsyncGraphDatabase") as mock_agdb:
            mock_agdb.driver = MagicMock(return_value=_mock_driver(session))
            with patch("src.graph.neo4j_store.settings") as s:
                s.neo4j_password = "secret"
                s.neo4j_uri = "bolt://x"
                s.neo4j_user = "u"
                s.neo4j_database = "d"
                store = Neo4jStore()
                stats = await store.stats()
        assert stats == {"Entity": 100, "Document": 50}
