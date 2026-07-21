CREATE INDEX IF NOT EXISTS idx_activity_events_job_created
ON activity_events(job_id, created_at DESC);
