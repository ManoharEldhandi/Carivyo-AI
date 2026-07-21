from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db import Database
from app.services.resume import ResumeService
from app.services.search import SearchService
from app.utils import json_dumps, new_id


class ApplicationBlocked(ValueError):
    pass


class ApplicationService:
    ALLOWED_TRANSITIONS = {
        "draft": {"opened", "applied", "withdrawn"},
        "opened": {"draft", "applied", "withdrawn"},
        "applied": {"interview", "offer", "rejected", "withdrawn"},
        "interview": {"offer", "rejected", "withdrawn"},
        "offer": {"withdrawn"},
        "rejected": set(),
        "withdrawn": set(),
    }

    def __init__(
        self,
        database: Database,
        search: SearchService,
        resumes: ResumeService,
    ):
        self.database = database
        self.search = search
        self.resumes = resumes

    async def prepare(
        self,
        job_id: str,
        resume_run_id: Optional[str],
        notes: Optional[str],
    ) -> Dict[str, Any]:
        job = await self.search.revalidate(job_id)
        if job["live_state"] != "live":
            raise ApplicationBlocked("The official application route is not currently live")
        existing = self.database.fetch_one(
            """
            SELECT * FROM applications
            WHERE job_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_id,),
        )
        if existing:
            effective_resume_run_id = (
                resume_run_id
                if resume_run_id is not None
                else existing["resume_run_id"]
            )
            effective_variant = None
            effective_pdf_hash = None
            if effective_resume_run_id is not None:
                verified = self._verify_resume_for_job(
                    effective_resume_run_id, job_id
                )
                effective_variant, effective_pdf_hash = self._resume_binding(verified)
            with self.database.transaction() as connection:
                current = connection.execute(
                    "SELECT * FROM applications WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
                if not current:
                    raise KeyError("Application not found")
                current = dict(current)
                effective_notes = notes if notes is not None else current["notes"]
                association_changed = any(
                    (
                        effective_resume_run_id != current["resume_run_id"],
                        effective_variant != current.get("resume_variant"),
                        effective_pdf_hash != current.get("resume_pdf_hash"),
                    )
                )
                if association_changed and current["status"] not in {
                    "draft",
                    "opened",
                }:
                    raise ApplicationBlocked(
                        "The submitted application's approved resume association is immutable"
                    )
                connection.execute(
                    """
                    UPDATE applications
                    SET resume_run_id = ?, resume_variant = ?, resume_pdf_hash = ?,
                        notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        effective_resume_run_id,
                        effective_variant,
                        effective_pdf_hash,
                        effective_notes,
                        existing["id"],
                    ),
                )
                if association_changed:
                    connection.execute(
                        """
                        INSERT INTO activity_events(
                            id, event_type, job_id, reason, metadata_json
                        ) VALUES (?, 'application_resume_changed', ?, ?, ?)
                        """,
                        (
                            new_id(),
                            job_id,
                            "Approved resume association changed before submission",
                            json_dumps(
                                {
                                    "application_id": existing["id"],
                                    "from_resume_run_id": current["resume_run_id"],
                                    "to_resume_run_id": effective_resume_run_id,
                                    "from_variant": current.get("resume_variant"),
                                    "to_variant": effective_variant,
                                    "from_pdf_hash": current.get("resume_pdf_hash"),
                                    "to_pdf_hash": effective_pdf_hash,
                                }
                            ),
                        ),
                    )
            return self.get(existing["id"])
        resume_variant = None
        resume_pdf_hash = None
        if resume_run_id is not None:
            verified = self._verify_resume_for_job(resume_run_id, job_id)
            resume_variant, resume_pdf_hash = self._resume_binding(verified)
        application_id = new_id()
        self.database.execute(
            """
            INSERT INTO applications(
                id, job_id, resume_run_id, resume_variant, resume_pdf_hash,
                status, notes
            ) VALUES (?, ?, ?, ?, ?, 'draft', ?)
            """,
            (
                application_id,
                job_id,
                resume_run_id,
                resume_variant,
                resume_pdf_hash,
                notes or "",
            ),
        )
        return self.get(application_id)

    async def open(self, job_id: str) -> Dict[str, Any]:
        job = await self.search.revalidate(job_id)
        if job["live_state"] != "live":
            raise ApplicationBlocked("The official application route is no longer live")
        application = self.database.fetch_one(
            """
            SELECT * FROM applications
            WHERE job_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (job_id,),
        )
        if not application:
            application = await self.prepare(job_id, None, "")
        if application.get("resume_run_id"):
            application = self._verify_application_binding(application, job_id)
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE applications
                SET status = CASE WHEN status = 'draft' THEN 'opened' ELSE status END,
                    opened_at = COALESCE(opened_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (application["id"],),
            )
            if application["status"] == "draft":
                connection.execute(
                    """
                    INSERT INTO activity_events(
                        id, event_type, job_id, reason, metadata_json
                    ) VALUES (?, 'application_status_changed', ?, ?, ?)
                    """,
                    (
                        new_id(),
                        job_id,
                        "Official application route opened by the user",
                        json_dumps(
                            {
                                "application_id": application["id"],
                                "from": "draft",
                                "to": "opened",
                            }
                        ),
                    ),
                )
        return {
            "application": self.get(application["id"]),
            "official_url": job["apply_url"],
            "warning": "You are leaving Carivyo. Review the official form and submit it yourself.",
        }

    def _verify_resume_for_job(
        self, resume_run_id: str, job_id: str
    ) -> Dict[str, Any]:
        resume = self.resumes.verify_ready_for_handoff(resume_run_id)
        if resume["job_id"] != job_id:
            raise ApplicationBlocked("The approved resume belongs to a different job")
        return resume

    @staticmethod
    def _resume_binding(resume: Dict[str, Any]) -> tuple[int, str]:
        result = resume.get("result", {})
        variant = result.get("variant")
        pdf_hash = result.get("provenance", {}).get("pdf_hash")
        if not isinstance(variant, int) or variant < 1 or not pdf_hash:
            raise ApplicationBlocked("The approved resume has no verifiable artifact binding")
        return variant, str(pdf_hash)

    def _verify_application_binding(
        self, application: Dict[str, Any], job_id: str
    ) -> Dict[str, Any]:
        verified = self._verify_resume_for_job(application["resume_run_id"], job_id)
        variant, pdf_hash = self._resume_binding(verified)
        stored_variant = application.get("resume_variant")
        stored_pdf_hash = application.get("resume_pdf_hash")
        if stored_variant is None and stored_pdf_hash is None and application["status"] in {
            "draft",
            "opened",
        }:
            self.database.execute(
                """
                UPDATE applications
                SET resume_variant = ?, resume_pdf_hash = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (variant, pdf_hash, application["id"]),
            )
            return self.get(application["id"])
        if stored_variant != variant or stored_pdf_hash != pdf_hash:
            raise ApplicationBlocked(
                "The approved resume artifact changed; review and associate the current version"
            )
        return application

    def update(self, application_id: str, status: str, notes: Optional[str]) -> Dict[str, Any]:
        application = self.get(application_id)
        current = application["status"]
        if status != current and status not in self.ALLOWED_TRANSITIONS.get(current, set()):
            raise ApplicationBlocked(
                f"Application cannot move directly from {current} to {status}"
            )
        if application.get("resume_run_id"):
            self._verify_application_binding(application, application["job_id"])
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE applications
                SET status = ?, notes = COALESCE(?, notes),
                    applied_at = CASE
                        WHEN ? = 'applied' THEN COALESCE(applied_at, CURRENT_TIMESTAMP)
                        ELSE applied_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, notes, status, application_id),
            )
            if status != current:
                connection.execute(
                    """
                    INSERT INTO activity_events(
                        id, event_type, job_id, reason, metadata_json
                    ) VALUES (?, 'application_status_changed', ?, ?, ?)
                    """,
                    (
                        new_id(),
                        application["job_id"],
                        "User-controlled application status transition",
                        json_dumps(
                            {
                                "application_id": application_id,
                                "from": current,
                                "to": status,
                            }
                        ),
                    ),
                )
        return self.get(application_id)

    def get(self, application_id: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            """
            SELECT a.*, j.title, j.company, j.location, j.apply_url
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.id = ?
            """,
            (application_id,),
        )
        if not row:
            raise KeyError("Application not found")
        return {
            **row,
            "allowed_transitions": sorted(
                self.ALLOWED_TRANSITIONS.get(row["status"], set())
            ),
        }

    def list(self) -> List[Dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT a.*, j.title, j.company, j.location, j.apply_url
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            ORDER BY a.updated_at DESC
            """
        )
        return [
            {
                **row,
                "allowed_transitions": sorted(
                    self.ALLOWED_TRANSITIONS.get(row["status"], set())
                ),
            }
            for row in rows
        ]
