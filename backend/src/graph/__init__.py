"""GraphRAG knowledge graph module.

Exports the public API used by ingestion (builder), retrieval (Neo4jStore),
and the agent (extractor + normalizer helpers).
"""
from .builder import build_graph_for_articles
from .extractor import EntityRelationExtractor
from .neo4j_store import Neo4jStore
from .normalizer import (
    ALIAS_MAP,
    ENTITY_TYPES,
    STRIP_SUFFIXES,
    make_entity_id,
    normalize_entity,
    normalize_entity_name,
    normalize_relation,
)
from .schema import (
    EMBEDDING_DIM,
    ChunkNode,
    DocumentNode,
    Entity,
    EntityType,
    Relation,
)

__all__ = [
    # Builder
    "build_graph_for_articles",
    # Extractor
    "EntityRelationExtractor",
    # Store
    "Neo4jStore",
    # Normalizer
    "ALIAS_MAP",
    "ENTITY_TYPES",
    "STRIP_SUFFIXES",
    "make_entity_id",
    "normalize_entity",
    "normalize_entity_name",
    "normalize_relation",
    # Schema
    "EMBEDDING_DIM",
    "ChunkNode",
    "DocumentNode",
    "Entity",
    "EntityType",
    "Relation",
]
