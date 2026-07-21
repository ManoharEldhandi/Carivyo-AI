CREATE TABLE IF NOT EXISTS pending_preference_changes (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    source_message TEXT NOT NULL,
    updates_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_preference_changes_conversation
    ON pending_preference_changes(conversation_id, status, created_at DESC);
