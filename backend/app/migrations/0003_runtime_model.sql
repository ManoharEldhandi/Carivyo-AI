ALTER TABLE conversations ADD COLUMN model TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_runtime
    ON conversations(provider, model, updated_at DESC);
