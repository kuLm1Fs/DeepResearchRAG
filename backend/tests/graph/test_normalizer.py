"""Unit tests for graph.normalizer (no I/O, no LLM)."""

from src.graph.normalizer import (
    ALIAS_MAP,
    STRIP_SUFFIXES,
    make_entity_id,
    normalize_entity,
    normalize_entity_name,
    normalize_relation,
)


class TestNormalizeEntityName:
    """Test the core name canonicalization rules."""

    def test_lowercases_ascii(self):
        assert normalize_entity_name("Apple") == "苹果"  # also aliased

    def test_strips_corporate_suffixes(self):
        assert normalize_entity_name("Apple Inc.") == "苹果"
        assert normalize_entity_name("Apple Inc") == "苹果"
        assert normalize_entity_name("Apple Corporation") == "苹果"
        assert normalize_entity_name("Apple Limited") == "苹果"

    def test_strips_chinese_suffixes(self):
        assert normalize_entity_name("苹果公司") == "苹果"
        assert normalize_entity_name("阿里巴巴集团") == "阿里巴巴"
        assert normalize_entity_name("腾讯控股") == "腾讯"

    def test_applies_alias_map(self):
        assert normalize_entity_name("AAPL") == "苹果"
        assert normalize_entity_name("aapl") == "苹果"
        assert normalize_entity_name("MSFT") == "微软"
        assert normalize_entity_name("JD") == "京东"

    def test_preserves_chinese_case(self):
        # CJK characters are not affected by .lower() — should still alias
        assert normalize_entity_name("苹果") == "苹果"
        assert normalize_entity_name("腾讯") == "腾讯"

    def test_strips_whitespace(self):
        assert normalize_entity_name("  Apple  ") == "苹果"
        assert normalize_entity_name("\tGoogle\n") == "谷歌"

    def test_handles_empty(self):
        assert normalize_entity_name("") == ""

    def test_strip_suffixes_defined(self):
        # Sanity check on the suffix list
        assert "inc." in STRIP_SUFFIXES
        assert "公司" in STRIP_SUFFIXES
        assert "集团" in STRIP_SUFFIXES

    def test_alias_map_has_known_entries(self):
        # Sanity check on the alias map
        assert "apple" in ALIAS_MAP
        assert "aapl" in ALIAS_MAP
        assert ALIAS_MAP["apple"] == "苹果"
        assert ALIAS_MAP["alphabet"] == "谷歌"


class TestMakeEntityId:
    def test_apple_alias_collapses(self):
        # "Apple" and "AAPL" and "苹果公司" should all dedup to the same id
        assert (
            make_entity_id("Apple", "Company")
            == make_entity_id("AAPL", "Company")
            == make_entity_id("苹果公司", "Company")
        )

    def test_type_disambiguates(self):
        # Same name, different type → different id
        assert (
            make_entity_id("Apple", "Company")
            != make_entity_id("Apple", "Product")
        )

    def test_returns_string(self):
        eid = make_entity_id("Apple", "Company")
        assert isinstance(eid, str)
        assert ":" in eid


class TestNormalizeEntity:
    def test_valid_input(self):
        raw = {
            "name": "Apple",
            "type": "Company",
            "description": "Cupertino-based iPhone maker with Q3 earnings beat.",
        }
        ent = normalize_entity(raw, "chunk1")
        assert ent is not None
        assert ent.name == "苹果"
        assert ent.type == "Company"
        assert ent.entity_id == "苹果:Company"
        assert ent.source_chunk_ids == ["chunk1"]

    def test_rejects_invalid_type(self):
        raw = {
            "name": "X",
            "type": "Garbage",
            "description": "long enough description here.",
        }
        assert normalize_entity(raw, "c1") is None

    def test_rejects_short_description(self):
        raw = {
            "name": "Apple",
            "type": "Company",
            "description": "short",
        }
        assert normalize_entity(raw, "c1", min_description_length=10) is None

    def test_rejects_missing_fields(self):
        assert normalize_entity({"name": "X", "description": "x" * 20}, "c1") is None
        assert normalize_entity({"type": "Person", "description": "x" * 20}, "c1") is None
        assert normalize_entity({"name": "X", "type": "Person"}, "c1") is None

    def test_accepts_all_valid_types(self):
        from src.graph.schema import ENTITY_TYPES
        for t in ENTITY_TYPES:
            raw = {
                "name": "Test",
                "type": t,
                "description": "A test entity of valid type for unit test.",
            }
            ent = normalize_entity(raw, "c1")
            assert ent is not None, f"type {t} should be accepted"


class TestNormalizeRelation:
    def test_valid_input(self):
        raw = {
            "source": "Apple",
            "target": "Tim Cook",
            "type": "led_by",
            "description": "Apple is led by CEO Tim Cook since 2011.",
            "keywords": ["CEO", "LEADERSHIP", "Apple"],
            "weight": 0.9,
        }
        rel = normalize_relation(raw, "c1")
        assert rel is not None
        assert rel.source == "苹果"  # aliased
        assert rel.target == "tim cook"  # lowercased
        assert rel.type == "led_by"
        assert rel.weight == 0.9
        # Keywords should be deduped + lowercased
        assert set(rel.keywords) == {"ceo", "leadership", "apple"}
        assert rel.source_chunk_ids == ["c1"]

    def test_rejects_self_loop(self):
        raw = {
            "source": "Apple",
            "target": "Apple",
            "type": "self",
            "description": "self reference that should be filtered.",
        }
        assert normalize_relation(raw, "c1") is None

    def test_rejects_short_description(self):
        raw = {
            "source": "A",
            "target": "B",
            "type": "test",
            "description": "short",
        }
        assert normalize_relation(raw, "c1", min_description_length=10) is None

    def test_clamps_weight_above_one(self):
        raw = {
            "source": "A",
            "target": "B",
            "type": "test",
            "description": "normal relation with extreme weight.",
            "weight": 5.0,
        }
        rel = normalize_relation(raw, "c1")
        assert rel.weight == 1.0

    def test_clamps_weight_below_zero(self):
        raw = {
            "source": "A",
            "target": "B",
            "type": "test",
            "description": "normal relation with negative weight.",
            "weight": -1.0,
        }
        rel = normalize_relation(raw, "c1")
        assert rel.weight == 0.0

    def test_default_weight(self):
        raw = {
            "source": "A",
            "target": "B",
            "type": "test",
            "description": "normal relation with no weight.",
        }
        rel = normalize_relation(raw, "c1")
        assert rel.weight == 0.5

    def test_handles_keywords_as_non_list(self):
        raw = {
            "source": "A",
            "target": "B",
            "type": "test",
            "description": "normal relation with bad keywords.",
            "keywords": "not a list",
        }
        rel = normalize_relation(raw, "c1")
        assert rel.keywords == []
