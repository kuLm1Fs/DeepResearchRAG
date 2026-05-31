-- Migration: Create feedbacks table
CREATE TABLE IF NOT EXISTS feedbacks (
    id            SERIAL PRIMARY KEY,
    query_id      VARCHAR(64),
    query_text    VARCHAR(2048),
    rating        VARCHAR(16) NOT NULL CHECK (rating IN ('positive', 'negative')),
    reason        VARCHAR(64),
    comment       VARCHAR(1024),
    user_id       VARCHAR(64) NOT NULL,
    company_id    VARCHAR(64),
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_user    ON feedbacks(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_company ON feedbacks(company_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedbacks(created_at);
