ALTER TABLE external_ats_reports ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE external_ats_reports ADD COLUMN started_at TEXT;
ALTER TABLE external_ats_reports ADD COLUMN completed_at TEXT;
ALTER TABLE external_ats_reports ADD COLUMN adapter_version TEXT;
ALTER TABLE external_ats_reports ADD COLUMN report_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_external_ats_reports_status
    ON external_ats_reports(status, created_at);
