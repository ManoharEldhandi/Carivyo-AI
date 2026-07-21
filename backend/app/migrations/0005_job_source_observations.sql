CREATE TABLE IF NOT EXISTS job_source_observations (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    connector_id TEXT NOT NULL REFERENCES connectors(id),
    external_id TEXT NOT NULL,
    source_family TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    apply_url TEXT NOT NULL,
    posted_at TEXT,
    parser_version TEXT NOT NULL,
    raw_path TEXT,
    observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_job_source_observations_job
    ON job_source_observations(job_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_source_observations_connector
    ON job_source_observations(connector_id, observed_at DESC);
