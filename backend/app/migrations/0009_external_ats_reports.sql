CREATE TABLE IF NOT EXISTS external_ats_reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES resume_runs(id) ON DELETE CASCADE,
    engine TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    report_json TEXT NOT NULL DEFAULT '{}',
    artifact_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_external_ats_reports_run
    ON external_ats_reports(run_id, engine, created_at DESC);
