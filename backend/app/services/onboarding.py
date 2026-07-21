from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import UploadFile

from app.artifacts import ArtifactVault
from app.config import Settings
from app.db import Database
from app.schemas import OnboardingProfileReview, OnboardingQuestion
from app.services.preference_intelligence import interpret_onboarding_answer
from app.services.extraction import (
    ExtractionError,
    build_evidence,
    detect_kind,
    extract_in_subprocess,
)
from app.utils import json_dumps, json_loads, new_id, stable_hash, unique


def default_questions(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    role_tracks = unique(
        [str(track).strip() for track in summary.get("role_tracks", []) if str(track).strip()]
    )
    tracks = ", ".join(role_tracks[:3])
    questions: List[Dict[str, Any]] = []
    # Ask for role ordering only when extraction leaves a real choice. A single
    # evidence-backed track is accepted as a reviewable default instead of
    # spending another onboarding turn on a low-information question.
    if len(role_tracks) > 1:
        questions.append({
            "id": "role_focus",
            "prompt": "What kind of role should I prioritize first?",
            "reason": f"Your resume supports {tracks or 'several directions'}, so this sets the first search order.",
            "example": "Backend or AI/LLM engineering; decide for me if both fit.",
            "skippable": True,
        })
    questions.extend([
        {
            "id": "preferred_locations",
            "prompt": "Which locations should come first, in order?",
            "reason": "Location order breaks close ranking ties and prevents one city from dominating.",
            "example": "Bengaluru, Hyderabad, then Remote India.",
            "skippable": False,
        },
        {
            "id": "work_mode",
            "prompt": "How open are you to remote, hybrid, onsite, or relocation?",
            "reason": "This controls location eligibility without adding a large filter form.",
            "example": "Remote or hybrid preferred; onsite is okay in Bengaluru.",
            "skippable": True,
        },
        {
            "id": "seniority",
            "prompt": "How much seniority stretch should I allow?",
            "reason": "This prevents obviously senior roles while keeping reasonable stretch opportunities.",
            "example": "Fresher to 2 years, including SDE I and associate roles.",
            "skippable": True,
        },
        {
            "id": "exclusions",
            "prompt": "Anything I should strongly avoid?",
            "reason": "Clear exclusions save more search time than another positive preference.",
            "example": "Avoid frontend-heavy, sales, night-shift, and unpaid roles.",
            "skippable": True,
        },
    ])
    return questions


class OnboardingService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        vault: ArtifactVault,
    ):
        self.settings = settings
        self.database = database
        self.vault = vault

    async def import_resume(self, upload: UploadFile) -> Dict[str, Any]:
        content = await upload.read(self.settings.max_upload_bytes + 1)
        if len(content) > self.settings.max_upload_bytes:
            raise ExtractionError("Resume exceeds the 10 MB upload limit")
        if not upload.filename:
            raise ExtractionError("The uploaded resume needs a filename")
        kind = detect_kind(upload.filename, content)
        source_path, content_hash = self.vault.store_upload(upload.filename, content)

        existing = self.database.fetch_one(
            "SELECT * FROM source_artifacts WHERE content_hash = ?",
            (content_hash,),
        )
        if existing:
            artifact_id = existing["id"]
            text = Path(existing["text_path"]).read_text(encoding="utf-8")
            claims, summary = build_evidence(text)
        else:
            text = extract_in_subprocess(source_path, kind)
            text_path = self.vault.write_text(
                f"imports/{content_hash}/extracted.txt", text
            )
            artifact_id = new_id()
            claims, summary = build_evidence(text)
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO source_artifacts(
                        id, original_name, kind, content_hash, source_path,
                        text_path, size_bytes, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'extracted')
                    """,
                    (
                        artifact_id,
                        upload.filename,
                        kind,
                        content_hash,
                        str(source_path),
                        str(text_path),
                        len(content),
                    ),
                )
                for claim in claims:
                    connection.execute(
                        """
                        INSERT INTO evidence_claims(
                            id, artifact_id, category, text, source_location,
                            approval, confidence
                        ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (
                            new_id(),
                            artifact_id,
                            claim["category"],
                            claim["text"],
                            claim["source_location"],
                            claim["confidence"],
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO resume_bases(
                        id, artifact_id, track, source_path, text_path,
                        content_hash, editable_kind, usable_for_tailoring
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id(),
                        artifact_id,
                        summary["role_tracks"][0],
                        str(source_path),
                        str(text_path),
                        content_hash,
                        kind,
                        1 if kind in {"markdown", "text"} else 0,
                    ),
                )

        questions = default_questions(summary)
        session_id = new_id()
        self.database.execute(
            """
            INSERT INTO onboarding_sessions(
                id, status, artifact_ids_json, summary_json, questions_json
            ) VALUES (?, 'questions', ?, ?, ?)
            """,
            (
                session_id,
                json_dumps([artifact_id]),
                json_dumps(summary),
                json_dumps(questions),
            ),
        )
        return self.get_state(session_id)

    def get_state(self, session_id: str) -> Dict[str, Any]:
        session = self.database.fetch_one(
            "SELECT * FROM onboarding_sessions WHERE id = ?",
            (session_id,),
        )
        if not session:
            raise KeyError("Onboarding session not found")
        questions = json_loads(session["questions_json"], [])
        index = session["current_index"]
        question = questions[index] if index < len(questions) else None
        return {
            "session_id": session_id,
            "status": session["status"],
            "summary": json_loads(session["summary_json"], {}),
            "conflicts": [],
            "question": question,
            "progress": {"answered": index, "total": len(questions)},
        }

    def answer(self, session_id: str, question_id: str, answer: str) -> Dict[str, Any]:
        session = self.database.fetch_one(
            "SELECT * FROM onboarding_sessions WHERE id = ?",
            (session_id,),
        )
        if not session:
            raise KeyError("Onboarding session not found")
        questions = json_loads(session["questions_json"], [])
        index = session["current_index"]
        if index >= len(questions) or questions[index]["id"] != question_id:
            raise ValueError("This onboarding question is no longer active")
        summary = json_loads(session["summary_json"], {})
        interpreted = interpret_onboarding_answer(question_id, answer, summary)
        answers = json_loads(session["answers_json"], {})
        answers[question_id] = {
            "raw": answer,
            "interpreted": interpreted,
        }
        next_index = index + 1
        status = "ready_to_confirm" if next_index >= len(questions) else "questions"
        self.database.execute(
            """
            UPDATE onboarding_sessions
            SET answers_json = ?, current_index = ?, status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json_dumps(answers), next_index, status, session_id),
        )
        next_question = questions[next_index] if next_index < len(questions) else None
        return {
            "status": status,
            "interpreted_answer": interpreted,
            "question": next_question,
            "progress": {"answered": next_index, "total": len(questions)},
        }

    def confirm(
        self,
        session_id: str,
        profile_review: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not profile_review:
            raise ValueError("Review the extracted profile before confirmation")
        profile_review = OnboardingProfileReview.model_validate(
            profile_review
        ).model_dump()
        session = self.database.fetch_one(
            "SELECT * FROM onboarding_sessions WHERE id = ?",
            (session_id,),
        )
        if not session:
            raise KeyError("Onboarding session not found")
        if session["status"] not in {"ready_to_confirm", "complete"}:
            raise ValueError("Finish the adaptive questions before confirming")
        if session["status"] == "complete":
            return json_loads(
                self.database.fetch_one(
                    "SELECT value_json FROM settings WHERE key = 'onboarding_result'"
                )["value_json"],
                {},
            )

        artifact_ids = json_loads(session["artifact_ids_json"], [])
        summary = json_loads(session["summary_json"], {})
        parsed_summary_hash = stable_hash(summary)
        summary = {
            **summary,
            "name": profile_review["name"],
            "email": profile_review.get("email"),
            "phone": profile_review.get("phone"),
            "links": profile_review.get("links", []),
            "skills": profile_review.get("skills", []),
            "role_tracks": profile_review.get("role_tracks", []),
            "highlights": profile_review.get("highlights", []),
        }
        answers = json_loads(session["answers_json"], {})
        interpreted = [
            value["interpreted"] for value in answers.values() if value.get("interpreted")
        ]
        interpreted.extend(
            [
                {
                    "key": "location_policy",
                    "value": "strict",
                    "kind": "hard",
                    "source": "product_default",
                },
                {
                    "key": "freshness_hours",
                    "value": 48,
                    "kind": "hard",
                    "source": "product_default",
                },
                {
                    "key": "source_policy",
                    "value": "official_direct",
                    "kind": "hard",
                    "source": "product_default",
                },
            ]
        )
        claim_rows = self.database.fetch_all(
            "SELECT * FROM evidence_claims WHERE artifact_id IN ({})".format(
                ",".join("?" for _ in artifact_ids)
            ),
            artifact_ids,
        )
        approved_claim_ids = [claim["id"] for claim in claim_rows]
        preferences = {
            item["key"]: item["value"]
            for item in interpreted
        }
        profile = {
            "identity": {
                "name": summary.get("name"),
                "email": summary.get("email"),
                "phone": summary.get("phone"),
                "links": summary.get("links", []),
            },
            "skills": summary.get("skills", []),
            "role_families": preferences.get(
                "target_roles", summary.get("role_tracks", ["Software Engineer"])
            ),
            "highlights": summary.get("highlights", []),
            "approved_evidence_ids": approved_claim_ids,
            "source_artifact_ids": artifact_ids,
            "onboarding_session_id": session_id,
            "parsed_summary_hash": parsed_summary_hash,
            "confirmed_by_user": True,
        }
        profile_version = stable_hash(profile)
        capsule = self._build_capsule(profile)
        preference_version = stable_hash(interpreted)
        profile_id = new_id()

        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE evidence_claims SET approval = 'approved' WHERE artifact_id IN ({})".format(
                    ",".join("?" for _ in artifact_ids)
                ),
                artifact_ids,
            )
            connection.execute(
                "UPDATE profile_snapshots SET status = 'inactive' WHERE status = 'active'"
            )
            connection.execute(
                """
                INSERT INTO profile_snapshots(
                    id, version, profile_json, capsule, status
                ) VALUES (?, ?, ?, ?, 'active')
                ON CONFLICT(version) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    capsule = excluded.capsule,
                    status = 'active'
                """,
                (profile_id, profile_version, json_dumps(profile), capsule),
            )
            connection.execute("UPDATE preferences SET active = 0")
            for item in interpreted:
                connection.execute(
                    """
                    INSERT INTO preferences(
                        id, key, value_json, kind, source, confidence
                    ) VALUES (?, ?, ?, ?, ?, 1.0)
                    """,
                    (
                        new_id(),
                        item["key"],
                        json_dumps(item["value"]),
                        item["kind"],
                        item["source"],
                    ),
                )
            result = {
                "profile_version": profile_version,
                "preference_version": preference_version,
            }
            connection.execute(
                """
                INSERT INTO settings(key, value_json) VALUES ('active_profile_version', ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (json_dumps(profile_version),),
            )
            connection.execute(
                """
                INSERT INTO settings(key, value_json) VALUES ('onboarding_result', ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (json_dumps(result),),
            )
            connection.execute(
                """
                UPDATE onboarding_sessions
                SET status = 'complete', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (session_id,),
            )
        return result

    async def refresh_resume(self, upload: UploadFile) -> Dict[str, Any]:
        """Deprecated compatibility shim that cannot bypass user confirmation."""

        raise ValueError(
            "Direct resume replacement is disabled; use the preview and confirm endpoints"
        )

    async def preview_resume_refresh(self, upload: UploadFile) -> Dict[str, Any]:
        """Extract a replacement resume without changing any active candidate state."""

        active = self._active_profile()
        if not active:
            raise ValueError("Complete onboarding before replacing the active resume")
        imported = await self.import_resume(upload)
        session = self.database.fetch_one(
            "SELECT * FROM onboarding_sessions WHERE id = ?",
            (imported["session_id"],),
        )
        if not session:
            raise KeyError("Resume refresh session not found")
        artifact_ids = json_loads(session["artifact_ids_json"], [])
        if len(artifact_ids) != 1:
            raise ValueError("Replacement resume draft must contain exactly one artifact")
        summary = json_loads(session["summary_json"], {})
        artifact = self.database.fetch_one(
            "SELECT * FROM source_artifacts WHERE id = ?",
            (artifact_ids[0],),
        )
        if not artifact:
            raise ValueError("Replacement resume artifact is unavailable")
        reviewable_summary = self._reviewable_summary(summary)
        diff = self._profile_diff(active["profile"], reviewable_summary)
        draft = {
            "kind": "resume_replacement",
            "draft_id": session["id"],
            "base_profile_version": active["version"],
            "artifact_id": artifact["id"],
            "content_hash": artifact["content_hash"],
            "source_text_hash": self.vault.hash_file(Path(artifact["text_path"])),
            "parsed_summary_hash": stable_hash(summary),
            "preview_diff_hash": stable_hash(diff),
        }
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE onboarding_sessions
                SET status = 'needs_confirmation', questions_json = '[]',
                    answers_json = ?, current_index = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (json_dumps({"resume_refresh_draft": draft}), session["id"]),
            )
            connection.execute(
                """
                INSERT INTO activity_events(id, event_type, reason, metadata_json)
                VALUES (?, 'resume_replacement_previewed',
                        'awaiting_user_confirmation', ?)
                """,
                (
                    new_id(),
                    json_dumps(
                        {
                            "draft_id": session["id"],
                            "base_profile_version": active["version"],
                            "artifact_id": artifact["id"],
                            "content_hash": artifact["content_hash"],
                            "parsed_summary_hash": draft["parsed_summary_hash"],
                            "preview_diff_hash": draft["preview_diff_hash"],
                        }
                    ),
                ),
            )
        return {
            "draft_id": session["id"],
            "session_id": session["id"],
            "status": "needs_confirmation",
            "summary": reviewable_summary,
            "diff": diff,
        }

    def confirm_resume_refresh(
        self,
        draft_id: str,
        profile_review: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Atomically activate one reviewed replacement-resume draft."""

        session = self.database.fetch_one(
            "SELECT * FROM onboarding_sessions WHERE id = ?",
            (draft_id,),
        )
        if not session:
            raise KeyError("Replacement resume draft not found")
        draft = json_loads(session["answers_json"], {}).get(
            "resume_refresh_draft", {}
        )
        if session["status"] == "complete" and draft.get("kind") == "resume_replacement":
            raise ValueError(
                "Replacement resume draft was already confirmed; no changes were applied"
            )
        if session["status"] != "needs_confirmation" or draft.get("kind") != "resume_replacement":
            raise ValueError("Session is not a valid replacement resume draft")

        artifact_ids = json_loads(session["artifact_ids_json"], [])
        summary = json_loads(session["summary_json"], {})
        if (
            len(artifact_ids) != 1
            or draft.get("draft_id") != draft_id
            or draft.get("artifact_id") != artifact_ids[0]
            or draft.get("parsed_summary_hash") != stable_hash(summary)
        ):
            raise ValueError("Replacement resume draft failed its integrity check")
        artifact = self.database.fetch_one(
            "SELECT * FROM source_artifacts WHERE id = ?",
            (artifact_ids[0],),
        )
        if not artifact or artifact["content_hash"] != draft.get("content_hash"):
            raise ValueError("Replacement resume artifact failed its integrity check")
        source_path = Path(artifact["source_path"])
        text_path = Path(artifact["text_path"])
        if (
            not source_path.is_file()
            or self.vault.hash_file(source_path) != artifact["content_hash"]
            or not text_path.is_file()
            or self.vault.hash_file(text_path) != draft.get("source_text_hash")
        ):
            raise ValueError("Replacement resume files changed after preview")

        active = self._active_profile()
        if not active:
            raise ValueError("The active profile is unavailable")
        if active["version"] != draft.get("base_profile_version"):
            raise ValueError(
                "The active profile changed after preview; create a new replacement draft"
            )
        claim_rows = self.database.fetch_all(
            """
            SELECT * FROM evidence_claims
            WHERE artifact_id = ?
            ORDER BY created_at, id
            """,
            (artifact_ids[0],),
        )
        resume_base = self.database.fetch_one(
            "SELECT id FROM resume_bases WHERE artifact_id = ? ORDER BY created_at, id LIMIT 1",
            (artifact_ids[0],),
        )
        if not claim_rows or not resume_base:
            raise ValueError("Replacement resume draft has incomplete evidence")

        reviewed_summary = self._reviewable_summary(profile_review)
        previous_profile = active["profile"]
        identity = {
            **previous_profile.get("identity", {}),
            "name": reviewed_summary["name"],
            "email": reviewed_summary.get("email"),
            "phone": reviewed_summary.get("phone"),
            "links": reviewed_summary.get("links", []),
        }
        profile = {
            "identity": identity,
            "skills": reviewed_summary.get("skills", []),
            "role_families": reviewed_summary.get("role_tracks", []),
            "highlights": reviewed_summary.get("highlights", []),
            "approved_evidence_ids": [row["id"] for row in claim_rows],
            "source_artifact_ids": artifact_ids,
            "onboarding_session_id": draft_id,
            "resume_refresh": True,
            "confirmed_by_user": True,
            "supersedes_profile_version": active["version"],
            "parsed_summary_hash": draft["parsed_summary_hash"],
            "reviewed_summary_hash": stable_hash(reviewed_summary),
            "resume_provenance": {
                "draft_id": draft_id,
                "artifact_id": artifact["id"],
                "resume_base_id": resume_base["id"],
                "content_hash": artifact["content_hash"],
                "source_text_hash": draft["source_text_hash"],
            },
        }
        profile_version = stable_hash(profile)
        diff = self._profile_diff(previous_profile, reviewed_summary)
        confirmed_draft = {
            **draft,
            "confirmed_profile_version": profile_version,
            "reviewed_summary_hash": profile["reviewed_summary_hash"],
            "confirmation_diff_hash": stable_hash(diff),
        }
        with self.database.transaction() as connection:
            current_session = connection.execute(
                "SELECT status, answers_json FROM onboarding_sessions WHERE id = ?",
                (draft_id,),
            ).fetchone()
            current_draft = (
                json_loads(current_session["answers_json"], {}).get(
                    "resume_refresh_draft", {}
                )
                if current_session
                else {}
            )
            if not current_session:
                raise KeyError("Replacement resume draft not found")
            if current_session["status"] == "complete":
                raise ValueError(
                    "Replacement resume draft was already confirmed; no changes were applied"
                )
            if (
                current_session["status"] != "needs_confirmation"
                or current_draft != draft
            ):
                raise ValueError("Replacement resume draft changed before confirmation")
            current_active = connection.execute(
                """
                SELECT version FROM profile_snapshots
                WHERE status = 'active'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """
            ).fetchone()
            if (
                not current_active
                or current_active["version"] != draft["base_profile_version"]
            ):
                raise ValueError(
                    "The active profile changed after preview; create a new replacement draft"
                )
            connection.execute(
                "UPDATE evidence_claims SET approval = 'approved' WHERE artifact_id = ?",
                (artifact_ids[0],),
            )
            connection.execute(
                "UPDATE profile_snapshots SET status = 'inactive' WHERE status = 'active'"
            )
            connection.execute(
                """
                INSERT INTO profile_snapshots(
                    id, version, profile_json, capsule, status
                ) VALUES (?, ?, ?, ?, 'active')
                """,
                (
                    new_id(),
                    profile_version,
                    json_dumps(profile),
                    self._build_capsule(profile),
                ),
            )
            connection.execute(
                "UPDATE search_plans SET status = 'stale' WHERE status = 'active'"
            )
            connection.execute(
                """
                UPDATE onboarding_sessions
                SET status = 'complete', answers_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    json_dumps({"resume_refresh_draft": confirmed_draft}),
                    draft_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO activity_events(id, event_type, reason, metadata_json)
                VALUES (?, 'resume_replacement_confirmed',
                        'explicit_user_confirmation', ?)
                """,
                (
                    new_id(),
                    json_dumps(
                        {
                            "draft_id": draft_id,
                            "previous_profile_version": active["version"],
                            "profile_version": profile_version,
                            "artifact_id": artifact["id"],
                            "resume_base_id": resume_base["id"],
                            "content_hash": artifact["content_hash"],
                            "parsed_summary_hash": draft["parsed_summary_hash"],
                            "reviewed_summary_hash": profile[
                                "reviewed_summary_hash"
                            ],
                            "confirmation_diff_hash": confirmed_draft[
                                "confirmation_diff_hash"
                            ],
                            "approved_evidence_ids": profile[
                                "approved_evidence_ids"
                            ],
                        }
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO settings(key, value_json) VALUES ('active_profile_version', ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (json_dumps(profile_version),),
            )
        return {
            "draft_id": draft_id,
            "session_id": draft_id,
            "status": "confirmed",
            "profile_version": profile_version,
            "preserved_preferences": True,
            "summary": reviewed_summary,
            "diff": diff,
        }

    def _active_preferences(self) -> List[Dict[str, Any]]:
        return [
            {**row, "value": json_loads(row["value_json"], None)}
            for row in self.database.fetch_all(
                "SELECT * FROM preferences WHERE active = 1 ORDER BY created_at"
            )
        ]

    def _active_profile(self) -> Optional[Dict[str, Any]]:
        row = self.database.fetch_one(
            """
            SELECT * FROM profile_snapshots
            WHERE status = 'active'
            ORDER BY created_at DESC, id DESC LIMIT 1
            """
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "version": row["version"],
            "profile": json_loads(row["profile_json"], {}),
        }

    @staticmethod
    def _reviewable_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": summary.get("name") or "Candidate",
            "email": summary.get("email"),
            "phone": summary.get("phone"),
            "links": list(summary.get("links") or []),
            "skills": list(summary.get("skills") or []),
            "role_tracks": list(summary.get("role_tracks") or ["Software Engineer"]),
            "highlights": list(summary.get("highlights") or []),
        }

    @classmethod
    def _profile_diff(
        cls,
        active_profile: Dict[str, Any],
        summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        active_identity = active_profile.get("identity", {})
        next_identity = {
            "name": summary.get("name"),
            "email": summary.get("email"),
            "phone": summary.get("phone"),
            "links": summary.get("links", []),
        }
        identity_diff: Dict[str, List[Dict[str, Any]]] = {
            "added": [],
            "removed": [],
            "changed": [],
        }
        for field in ("name", "email", "phone", "links"):
            before = active_identity.get(field)
            after = next_identity.get(field)
            before_present = before not in (None, "", [])
            after_present = after not in (None, "", [])
            if not before_present and after_present:
                identity_diff["added"].append({"field": field, "value": after})
            elif before_present and not after_present:
                identity_diff["removed"].append({"field": field, "value": before})
            elif before != after:
                identity_diff["changed"].append(
                    {"field": field, "before": before, "after": after}
                )
        return {
            "identity": identity_diff,
            "skills": cls._list_diff(
                active_profile.get("skills", []), summary.get("skills", [])
            ),
            "role_tracks": cls._list_diff(
                active_profile.get("role_families", []),
                summary.get("role_tracks", []),
            ),
            "highlights": cls._list_diff(
                active_profile.get("highlights", []), summary.get("highlights", [])
            ),
        }

    @staticmethod
    def _list_diff(before: List[str], after: List[str]) -> Dict[str, Any]:
        before_by_key = {value.casefold(): value for value in before}
        after_by_key = {value.casefold(): value for value in after}
        shared_keys = before_by_key.keys() & after_by_key.keys()
        changed = [
            {"before": before_by_key[key], "after": after_by_key[key]}
            for key in sorted(shared_keys)
            if before_by_key[key] != after_by_key[key]
        ]
        before_order = [value.casefold() for value in before]
        after_order = [value.casefold() for value in after]
        if (
            set(before_order) == set(after_order)
            and before_order != after_order
        ):
            changed.append(
                {"before": ", ".join(before), "after": ", ".join(after)}
            )
        return {
            "added": sorted(
                (after_by_key[key] for key in after_by_key.keys() - before_by_key.keys()),
                key=str.casefold,
            ),
            "removed": sorted(
                (before_by_key[key] for key in before_by_key.keys() - after_by_key.keys()),
                key=str.casefold,
            ),
            "changed": changed,
        }

    @staticmethod
    def _build_capsule(profile: Dict[str, Any]) -> str:
        identity = profile["identity"]
        roles = ", ".join(profile.get("role_families", [])[:4])
        skills = ", ".join(profile.get("skills", [])[:18])
        highlights = " ".join(profile.get("highlights", [])[:3])
        return (
            f"{identity.get('name') or 'Candidate'} targets {roles or 'software roles'}. "
            f"Evidence-backed skills: {skills or 'not yet resolved'}. "
            f"Selected proof: {highlights or 'review the approved evidence ledger'}"
        ).strip()
