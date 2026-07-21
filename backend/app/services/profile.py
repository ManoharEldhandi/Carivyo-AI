from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.db import Database
from app.utils import json_dumps, json_loads, new_id, stable_hash


class ProfileService:
    def __init__(self, database: Database):
        self.database = database

    def active_profile(self) -> Optional[Dict[str, Any]]:
        row = self.database.fetch_one(
            """
            SELECT * FROM profile_snapshots
            WHERE status = 'active'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "version": row["version"],
            "profile": json_loads(row["profile_json"], {}),
            "capsule": row["capsule"],
            "created_at": row["created_at"],
        }

    def approved_evidence(
        self,
        limit: int = 200,
        profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        active = profile or self.active_profile()
        if not active:
            return []
        claim_ids = active["profile"].get("approved_evidence_ids", [])
        if not claim_ids:
            return []
        return self.database.fetch_all(
            f"""
            SELECT id, artifact_id, category, text, source_location, confidence
            FROM evidence_claims
            WHERE approval = 'approved'
              AND id IN ({",".join("?" for _ in claim_ids)})
            ORDER BY created_at, source_location
            LIMIT ?
            """,
            (*claim_ids, limit),
        )

    def active_resume_bases(
        self,
        profile: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        active = profile or self.active_profile()
        if not active:
            return []
        artifact_ids = active["profile"].get("source_artifact_ids", [])
        if not artifact_ids:
            return []
        return self.database.fetch_all(
            f"""
            SELECT rb.*, sa.original_name, sa.kind AS original_kind,
                   sa.size_bytes AS original_size_bytes
            FROM resume_bases AS rb
            JOIN source_artifacts AS sa ON sa.id = rb.artifact_id
            WHERE rb.artifact_id IN ({",".join("?" for _ in artifact_ids)})
            ORDER BY rb.created_at DESC, rb.id ASC
            """,
            artifact_ids,
        )

    def preferences(self) -> List[Dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT * FROM preferences
            WHERE active = 1
            ORDER BY created_at
            """
        )
        return [
            {
                **row,
                "value": json_loads(row["value_json"], None),
                "event_ids": json_loads(row["event_ids_json"], []),
            }
            for row in rows
        ]

    def preference_map(self) -> Dict[str, Any]:
        return {row["key"]: row["value"] for row in self.preferences()}

    def preference_version(self) -> str:
        compact = [
            {
                "key": row["key"],
                "value": row["value"],
                "kind": row["kind"],
                "confidence": row["confidence"],
            }
            for row in self.preferences()
        ]
        return stable_hash(compact)

    def profile_payload(self) -> Optional[Dict[str, Any]]:
        profile = self.active_profile()
        if not profile:
            return None
        return {
            **profile,
            "preferences": self.preferences(),
            "evidence": self.approved_evidence(limit=60, profile=profile),
            "resume_bases": [
                {
                    key: base[key]
                    for key in (
                        "id",
                        "track",
                        "source_path",
                        "text_path",
                        "editable_kind",
                        "usable_for_tailoring",
                        "created_at",
                    )
                }
                for base in self.active_resume_bases(profile=profile)
            ],
        }

    def update_profile(self, editable: Dict[str, Any]) -> Dict[str, Any]:
        """Create an immutable confirmed profile version without changing evidence."""

        active = self.active_profile()
        if not active:
            raise ValueError("Complete onboarding before editing the profile")
        previous = active["profile"]
        profile = {
            **previous,
            "identity": editable["identity"],
            "skills": editable.get("skills", []),
            "role_families": editable.get("role_families", []),
            "highlights": editable.get("highlights", []),
            "confirmed_by_user": True,
            "supersedes_profile_version": active["version"],
        }
        version = stable_hash(profile)
        changed_fields = [
            key
            for key in ("identity", "skills", "role_families", "highlights")
            if previous.get(key) != profile.get(key)
        ]
        if not changed_fields:
            payload = self.profile_payload()
            if not payload:
                raise ValueError("The active profile is unavailable")
            return payload
        capsule = self._build_capsule(profile)
        with self.database.transaction() as connection:
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
                (new_id(), version, json_dumps(profile), capsule),
            )
            connection.execute(
                "UPDATE search_plans SET status = 'stale' WHERE status = 'active'"
            )
            connection.execute(
                """
                INSERT INTO activity_events(id, event_type, reason, metadata_json)
                VALUES (?, 'profile_updated', 'explicit_user_edit', ?)
                """,
                (
                    new_id(),
                    json_dumps(
                        {
                            "previous_version": active["version"],
                            "profile_version": version,
                            "changed_fields": changed_fields,
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
                (json_dumps(version),),
            )
        payload = self.profile_payload()
        if not payload:
            raise ValueError("The updated profile is unavailable")
        return payload

    @staticmethod
    def _build_capsule(profile: Dict[str, Any]) -> str:
        identity = profile.get("identity", {})
        roles = ", ".join(profile.get("role_families", [])[:4])
        skills = ", ".join(profile.get("skills", [])[:18])
        highlights = " ".join(profile.get("highlights", [])[:3])
        return (
            f"{identity.get('name') or 'Candidate'} targets {roles or 'software roles'}. "
            f"Evidence-backed or user-confirmed skills: {skills or 'not yet resolved'}. "
            f"Selected proof: {highlights or 'review the approved evidence ledger'}"
        ).strip()
