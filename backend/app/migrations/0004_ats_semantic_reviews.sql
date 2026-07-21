CREATE TABLE IF NOT EXISTS ats_semantic_reviews (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES resume_runs(id) ON DELETE CASCADE,
    deterministic_analysis_id TEXT NOT NULL
        REFERENCES ats_analyses(id) ON DELETE RESTRICT,
    deterministic_analysis_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('running', 'complete', 'failed')),
    response_json TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    usage_kind TEXT NOT NULL DEFAULT 'unknown',
    latency_ms INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0 AND attempt_count <= 2),
    error_code TEXT,
    error TEXT,
    review_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    CHECK (
        (status = 'complete' AND response_json IS NOT NULL AND error IS NULL)
        OR (status = 'failed' AND response_json IS NULL AND error IS NOT NULL)
        OR (status = 'running' AND response_json IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_ats_semantic_reviews_run
    ON ats_semantic_reviews(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ats_semantic_reviews_analysis
    ON ats_semantic_reviews(deterministic_analysis_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ats_semantic_reviews_status
    ON ats_semantic_reviews(status, updated_at DESC);
