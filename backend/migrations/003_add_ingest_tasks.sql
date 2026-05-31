-- Migration 003: Add ingest_tasks table
-- Replaces in-memory dict for cross-worker task state

CREATE TABLE IF NOT EXISTS ingest_tasks (
    id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    source VARCHAR(64),
    user_id VARCHAR(64) NOT NULL,
    company_id VARCHAR(64),
    articles_collected INT DEFAULT 0,
    chunks_indexed INT DEFAULT 0,
    records_inserted INT DEFAULT 0,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ingest_user ON ingest_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_ingest_company ON ingest_tasks(company_id);
CREATE INDEX IF NOT EXISTS idx_ingest_status ON ingest_tasks(status);
