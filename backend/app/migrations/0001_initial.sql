CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_artifacts (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL,
    text_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS onboarding_sessions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    artifact_ids_json TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL DEFAULT '{}',
    current_index INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence_claims (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES source_artifacts(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    source_location TEXT NOT NULL,
    approval TEXT NOT NULL,
    confidence REAL NOT NULL,
    conflict_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_approval
    ON evidence_claims(approval, category);

CREATE TABLE IF NOT EXISTS resume_bases (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES source_artifacts(id) ON DELETE CASCADE,
    track TEXT NOT NULL,
    source_path TEXT NOT NULL,
    text_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    editable_kind TEXT NOT NULL,
    usable_for_tailoring INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profile_snapshots (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    profile_json TEXT NOT NULL,
    capsule TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    event_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_preferences_active
    ON preferences(active, key);

CREATE TABLE IF NOT EXISTS search_plans (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    profile_version TEXT NOT NULL,
    preference_version TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    status TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS connectors (
    id TEXT PRIMARY KEY,
    connector_type TEXT NOT NULL,
    name TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    config_json TEXT NOT NULL,
    trust_tier TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    health TEXT NOT NULL DEFAULT 'unknown',
    last_checked_at TEXT,
    parser_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_runs (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES search_plans(id),
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    coverage_json TEXT NOT NULL DEFAULT '{}',
    discovered_count INTEGER NOT NULL DEFAULT 0,
    verified_count INTEGER NOT NULL DEFAULT 0,
    ranked_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL REFERENCES connectors(id),
    external_id TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    description TEXT NOT NULL,
    description_hash TEXT NOT NULL,
    location TEXT NOT NULL,
    work_mode TEXT,
    employment_type TEXT,
    posted_at TEXT,
    posted_semantics TEXT,
    apply_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_family TEXT NOT NULL,
    salary_json TEXT,
    raw_path TEXT,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(connector_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_canonical
    ON jobs(canonical_key);
CREATE INDEX IF NOT EXISTS idx_jobs_last_seen
    ON jobs(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS job_verifications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    live_state TEXT NOT NULL,
    freshness_class TEXT NOT NULL,
    posting_evidence_json TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    http_status INTEGER,
    apply_host TEXT NOT NULL,
    verifier_version TEXT NOT NULL,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_verifications_job
    ON job_verifications(job_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS match_results (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_version TEXT NOT NULL,
    preference_version TEXT NOT NULL,
    score REAL NOT NULL,
    tier TEXT NOT NULL,
    factors_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    risks_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, profile_version, preference_version)
);

CREATE INDEX IF NOT EXISTS idx_match_score
    ON match_results(score DESC);

CREATE TABLE IF NOT EXISTS activity_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    provider TEXT,
    provider_session_id TEXT,
    rolling_summary TEXT NOT NULL DEFAULT '',
    context_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    entity_refs_json TEXT NOT NULL DEFAULT '{}',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    usage_kind TEXT NOT NULL DEFAULT 'estimated',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    entity_refs_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    prompt_hash TEXT,
    context_hash TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    usage_kind TEXT NOT NULL DEFAULT 'estimated',
    latency_ms INTEGER,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_runs (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    mode TEXT NOT NULL,
    base_resume_id TEXT REFERENCES resume_bases(id),
    custom_instructions TEXT NOT NULL,
    interpretation_json TEXT NOT NULL DEFAULT '[]',
    workspace_path TEXT NOT NULL,
    result_path TEXT,
    jd_hash TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    resume_run_id TEXT REFERENCES resume_runs(id),
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    opened_at TEXT,
    applied_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
