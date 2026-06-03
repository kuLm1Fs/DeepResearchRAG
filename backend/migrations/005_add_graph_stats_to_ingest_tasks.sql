-- Migration 005: Add graph build stats to ingest_tasks
-- Phase 2 of GraphRAG: tracks how many entities/relations the graph layer
-- pulled out of each ingest run, so callers can see the graph layer is
-- actually being exercised.

ALTER TABLE ingest_tasks
    ADD COLUMN IF NOT EXISTS graph_entities   INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS graph_relations  INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS graph_skipped    INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS graph_errors     INT DEFAULT 0;
