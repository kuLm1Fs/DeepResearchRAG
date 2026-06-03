"""Graph schema for GraphRAG knowledge graph (LightRAG-style).

Node types: Document, Chunk, Entity
Edge types: PART_OF (Chunk -> Document), MENTIONED_IN (Entity -> Chunk), RELATION (Entity -> Entity)

Entity types are constrained to a fixed enum so the LLM extractor can be
prompted precisely and so retrieval can filter by type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, get_args

# Entity type enum. Order is the canonical order used in prompts and logs.
EntityType = Literal[
    "Person",
    "Company",
    "Product",
    "Event",
    "Metric",
    "Location",
    "Concept",
]
ENTITY_TYPES: tuple[str, ...] = get_args(EntityType)
#: Number of entity types exposed to the LLM (used in prompt construction).
NUM_ENTITY_TYPES = len(ENTITY_TYPES)

EMBEDDING_DIM = 1024  # matches 火山引擎 doubao-embedding output


# ---------------------------------------------------------------------------
# Data classes (Python side; the wire format from LLM extractor)
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    """One extracted entity. `entity_id` is the canonical dedup key."""
    entity_id: str
    name: str
    type: EntityType
    description: str
    embedding: list[float] | None = None
    mention_count: int = 1
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class Relation:
    """One extracted relation between two entities (by canonical name)."""
    source: str  # entity canonical name
    target: str  # entity canonical name
    type: str    # e.g. "invested_in", "competes_with", "located_in"
    description: str
    keywords: list[str] = field(default_factory=list)
    weight: float = 0.5
    source_chunk_ids: list[str] = field(default_factory=list)


@dataclass
class ChunkNode:
    """A text chunk that lives in the graph for back-traversal from entities."""
    chunk_id: str
    content: str
    position: int
    parent_doc_id: str
    embedding: list[float] | None = None


@dataclass
class DocumentNode:
    """The source document for a chunk."""
    doc_id: str
    title: str
    source: str
    published_at: int
    url: str = ""
    language: str = ""


# ---------------------------------------------------------------------------
# Cypher query templates
# ---------------------------------------------------------------------------
# Keep these as constants (not f-strings) so they're easy to grep, log, and
# inspect in test failures. Parameters use $name for neo4j driver binding.

CREATE_VECTOR_INDEX_ENTITY = """
CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
FOR (n:Entity) ON (n.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: $dim,
  `vector.similarity_function`: 'cosine'
}}
""".strip()

CREATE_FULLTEXT_INDEX_ENTITY = """
CREATE FULLTEXT INDEX entity_name_desc IF NOT EXISTS
FOR (n:Entity) ON EACH [n.name, n.description]
""".strip()

CREATE_FULLTEXT_INDEX_RELATION = """
CREATE FULLTEXT INDEX relation_keywords IF NOT EXISTS
FOR ()-[r:RELATION]-() ON EACH [r.keywords, r.description]
""".strip()

CREATE_INDEX_ENTITY_NAME = (
    "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)"
)

UPSERT_ENTITY = """
MERGE (e:Entity {entity_id: $entity_id})
ON CREATE SET
  e.name = $name,
  e.type = $type,
  e.description = $description,
  e.embedding = $embedding,
  e.mention_count = 1
ON MATCH SET
  e.name = $name,
  e.description = $description,
  e.embedding = COALESCE($embedding, e.embedding),
  e.mention_count = e.mention_count + 1
RETURN e.entity_id AS entity_id
""".strip()

# Note: we deliberately don't try to merge keyword lists inside Cypher — that
# would require APOC. List accumulation is done client-side in Python.

UPSERT_RELATION = """
MATCH (s:Entity {entity_id: $source_id})
MATCH (t:Entity {entity_id: $target_id})
MERGE (s)-[r:RELATION {type: $type, source: $source_id, target: $target_id}]->(t)
ON CREATE SET
  r.description = $description,
  r.keywords = $keywords,
  r.weight = $weight,
  r.source_chunk_ids = $source_chunk_ids
ON MATCH SET
  r.description = $description,
  r.keywords = $keywords,
  r.weight = CASE WHEN $weight > r.weight THEN $weight ELSE r.weight END
""".strip()

LINK_ENTITY_TO_CHUNK = """
MATCH (c:Chunk {chunk_id: $chunk_id})
MATCH (e:Entity {entity_id: $entity_id})
MERGE (e)-[m:MENTIONED_IN]->(c)
ON CREATE SET m.first_seen = timestamp()
""".strip()

LINK_CHUNK_TO_DOC = """
MATCH (c:Chunk {chunk_id: $chunk_id})
MATCH (d:Document {doc_id: $doc_id})
MERGE (c)-[:PART_OF]->(d)
""".strip()

# Read queries used by GraphRetriever (Phase 3)
VECTOR_SEARCH_ENTITIES = """
CALL db.index.vector.queryNodes('entity_embedding', $top_k, $embedding)
YIELD node, score
RETURN node.entity_id AS entity_id,
       node.name AS name,
       node.type AS type,
       node.description AS description,
       score
ORDER BY score DESC
""".strip()

ENTITY_NEIGHBORS_AND_CHUNKS = """
MATCH (e:Entity {entity_id: $entity_id})
      -[m:MENTIONED_IN]->(c:Chunk)
      -[p:PART_OF]->(d:Document)
OPTIONAL MATCH (e)-[r:RELATION]->(other:Entity)
RETURN c.chunk_id AS chunk_id,
       c.content AS content,
       d.title AS title,
       d.url AS url,
       d.source AS source,
       collect(DISTINCT {
         type: r.type,
         target: other.name,
         weight: r.weight
       }) AS via_relations
""".strip()

FULLTEXT_SEARCH_RELATIONS = """
CALL db.index.fulltext.queryRelationships('relation_keywords', $query, {limit: $top_k})
YIELD relationship, score
MATCH (s:Entity)-[relationship]->(t:Entity)
MATCH (s)-[:MENTIONED_IN]->(c:Chunk)-[:PART_OF]->(d:Document)
RETURN DISTINCT c.chunk_id AS chunk_id,
       c.content AS content,
       d.title AS title,
       d.url AS url,
       d.source AS source,
       relationship.type AS relation_type,
       s.name AS source_entity,
       t.name AS target_entity,
       score
ORDER BY score DESC
""".strip()

GRAPH_STATS = """
MATCH (n)
RETURN labels(n)[0] AS label, count(n) AS count
""".strip()

# -----------------------------------------------------------------------
# Phase 5: graph introspection queries (entity detail page / graph viz)
# -----------------------------------------------------------------------

# Subgraph around an entity, 1 or 2 hops. We cap relations to keep payloads
# bounded for the frontend — graph viz is a browsing affordance, not retrieval.
ENTITY_SUBGRAPH = """
MATCH (e:Entity)
WHERE e.name = $name OR e.entity_id = $entity_id
OPTIONAL MATCH (e)-[r1:RELATION]-(n1:Entity)
WITH e,
     collect(DISTINCT {
       type: r1.type,
       target_id: n1.entity_id,
       target_name: n1.name,
       target_type: n1.type,
       weight: r1.weight,
       description: r1.description
     }) AS rels_1
OPTIONAL MATCH (e)-[m:MENTIONED_IN]->(c:Chunk)-[:PART_OF]->(d:Document)
WITH e, rels_1,
     collect(DISTINCT {
       chunk_id: c.chunk_id,
       content: c.content,
       title: d.title,
       url: d.url,
       source: d.source
     })[0..5] AS sample_chunks
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.type AS type,
       e.description AS description,
       e.mention_count AS mention_count,
       rels_1 AS relations,
       sample_chunks AS sample_chunks
""".strip()

# Entities + outgoing relations for a single chunk (used by SourceCard
# "relations" popover on the frontend).
CHUNK_GRAPH = """
MATCH (c:Chunk {chunk_id: $chunk_id})
MATCH (e:Entity)-[:MENTIONED_IN]->(c)
OPTIONAL MATCH (e)-[r:RELATION]->(other:Entity)
WHERE (other)-[:MENTIONED_IN]->(c)
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.type AS type,
       collect(DISTINCT {
         type: r.type,
         target: other.name
       }) AS relations
""".strip()

# Most-mentioned entities — for the "Browse" landing view when a user
# hasn't asked a query yet.
TOP_ENTITIES = """
MATCH (e:Entity)
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.type AS type,
       e.mention_count AS mention_count
ORDER BY e.mention_count DESC
LIMIT $limit
""".strip()
