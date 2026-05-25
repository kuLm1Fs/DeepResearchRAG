-- Add current_step tracking for long-running Deep Research tasks.
-- Idempotent so it can be applied safely in existing dev/prod databases.

ALTER TABLE research_tasks
ADD COLUMN IF NOT EXISTS current_step VARCHAR(32);
