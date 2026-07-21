CREATE TABLE IF NOT EXISTS search_run_jobs (
    run_id TEXT NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, job_id)
);

CREATE INDEX IF NOT EXISTS idx_search_run_jobs_order
    ON search_run_jobs(run_id, ordinal, job_id);
