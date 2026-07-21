CREATE TABLE IF NOT EXISTS ats_analyses (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES resume_runs(id) ON DELETE CASCADE,
    analyzer_version TEXT NOT NULL,
    score REAL NOT NULL CHECK (score >= 0 AND score <= 100),
    analysis_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ats_analyses_run
    ON ats_analyses(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ats_analyses_version_score
    ON ats_analyses(analyzer_version, score DESC);
