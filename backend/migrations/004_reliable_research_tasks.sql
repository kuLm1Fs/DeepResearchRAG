-- Phase 3: reliable long-running research tasks.
-- Adds retry, worker lease, heartbeat, cancellation and dead-letter tracking.

ALTER TABLE research_tasks
DROP CONSTRAINT IF EXISTS research_tasks_status_check;

ALTER TABLE research_tasks
ADD CONSTRAINT research_tasks_status_check
CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'dead_letter'));

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0;

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3;

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS locked_by VARCHAR(128);

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP;

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMP;

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS dead_letter_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_tasks_lease
ON research_tasks(status, heartbeat_at);
