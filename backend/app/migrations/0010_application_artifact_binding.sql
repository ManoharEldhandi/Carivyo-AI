ALTER TABLE applications ADD COLUMN resume_variant INTEGER;
ALTER TABLE applications ADD COLUMN resume_pdf_hash TEXT;

ALTER TABLE external_ats_reports ADD COLUMN variant INTEGER;
ALTER TABLE external_ats_reports ADD COLUMN resume_pdf_hash TEXT;
ALTER TABLE external_ats_reports ADD COLUMN job_description_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_applications_resume_binding
    ON applications(resume_run_id, resume_variant, resume_pdf_hash);
