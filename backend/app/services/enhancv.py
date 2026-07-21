from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import SecretStr

from app.artifacts import ArtifactVault
from app.config import Settings
from app.db import Database
from app.utils import json_dumps, json_loads, new_id


class EnhancvUnavailable(RuntimeError):
    pass


class EnhancvATSService:
    """Controlled bridge to the user's authorized Enhancv checker session.

    The third-party checker runs only after explicit UI consent. Its HTML,
    screenshots, logs, and generic intermediate report live in a temporary
    directory and are deleted when the subprocess finishes. Carivyo persists
    one compact final report tied to the exact resume and JD hashes.
    """

    ENGINE = "enhancv"

    def __init__(self, settings: Settings, database: Database, vault: ArtifactVault):
        self.settings = settings
        self.database = database
        self.vault = vault

    def availability(self) -> Dict[str, Any]:
        script = self._script_path()
        repo = self.settings.resolved_enhancv_playwright_repo
        email = (self.settings.enhancv_email or "").strip()
        password = self._password()
        reasons = []
        if not script or not script.is_file():
            reasons.append("checker script is not configured")
        if not email:
            reasons.append("email is not configured")
        if self.settings.enhancv_use_keychain and not self._keychain_configured(email):
            reasons.append("Enhancv Keychain credential is unavailable")
        elif not password and not self.settings.enhancv_use_keychain:
            reasons.append("password is not configured")
        if not (repo / "package.json").is_file():
            reasons.append("Playwright project is unavailable")
        if not shutil.which("node"):
            reasons.append("Node.js is unavailable")
        return {
            "id": self.ENGINE,
            "label": "Enhancv",
            "available": not reasons,
            "external": True,
            "configured": not reasons,
            "reason": "; ".join(reasons) if reasons else "Ready through the authorized local account",
            "sends_full_documents": True,
        }

    def start(self, run_id: str) -> Dict[str, Any]:
        availability = self.availability()
        if not availability["available"]:
            raise EnhancvUnavailable(availability["reason"])
        run = self._run(run_id)
        if run["status"] not in {"needs_user_review", "ready_to_apply"}:
            raise EnhancvUnavailable("Finish generating the resume before running Enhancv")
        result = json_loads(run.get("result_json"), {})
        variant, pdf_hash, jd_hash = self._binding(result)
        workspace = Path(run["workspace_path"]).resolve()
        stale_final = workspace / "reports" / "enhancv-final.json"
        try:
            stale_final.relative_to(workspace)
            stale_final.unlink(missing_ok=True)
        except ValueError as exc:
            raise EnhancvUnavailable("The resume workspace is invalid") from exc
        report_id = new_id()
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM external_ats_reports WHERE run_id = ? AND engine = ?",
                (run_id, self.ENGINE),
            )
            connection.execute(
                """
                INSERT INTO external_ats_reports(
                    id, run_id, variant, resume_pdf_hash,
                    job_description_hash, engine, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'running')
                """,
                (report_id, run_id, variant, pdf_hash, jd_hash, self.ENGINE),
            )
        return self.get(report_id)

    def execute(self, report_id: str) -> None:
        row = self.database.fetch_one(
            "SELECT * FROM external_ats_reports WHERE id = ?", (report_id,)
        )
        if not row or row["status"] != "running":
            return
        try:
            run = self._run(row["run_id"])
            result = json_loads(run.get("result_json"), {})
            variant, pdf_hash, jd_hash = self._binding(result)
            if (
                variant != row["variant"]
                or pdf_hash != row["resume_pdf_hash"]
                or jd_hash != row["job_description_hash"]
            ):
                raise EnhancvUnavailable(
                    "The resume or job description changed after consent; confirm the current version"
                )
            workspace = Path(run["workspace_path"]).resolve()
            artifacts = result.get("artifacts", {})
            pdf = self._confined_file(workspace, artifacts.get("pdf"), "resume PDF")
            jd = self._confined_file(
                workspace,
                workspace / "inputs" / "job-description.txt",
                "job description",
            )
            script = self._script_path()
            if not script:
                raise EnhancvUnavailable("checker script is not configured")

            with tempfile.TemporaryDirectory(
                prefix="enhancv-", dir=self.settings.runtime_dir
            ) as temporary:
                temporary_path = Path(temporary)
                text_out = temporary_path / "report.txt"
                json_out = temporary_path / "report.json"
                html_out = temporary_path / "report.html"
                screenshot_out = temporary_path / "report.png"
                command = [
                    sys.executable,
                    str(script),
                    "--repo",
                    str(self.settings.resolved_enhancv_playwright_repo),
                    "--pdf",
                    str(pdf),
                    "--job-description-file",
                    str(jd),
                    "--out",
                    str(text_out),
                    "--json",
                    str(json_out),
                    "--html",
                    str(html_out),
                    "--screenshot",
                    str(screenshot_out),
                    "--profile",
                    str(self.settings.resolved_enhancv_profile_dir),
                    "--email-env",
                    "CARIVYO_ENHANCV_EMAIL",
                    "--password-env",
                    "CARIVYO_ENHANCV_PASSWORD",
                    "--headless" if self.settings.enhancv_headless else "--headed",
                ]
                if not self.settings.enhancv_use_keychain:
                    command.append("--no-keychain")
                env = {
                    key: os.environ[key]
                    for key in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "USER")
                    if key in os.environ
                }
                env["CARIVYO_ENHANCV_EMAIL"] = self.settings.enhancv_email or ""
                env["CARIVYO_ENHANCV_PASSWORD"] = (
                    "" if self.settings.enhancv_use_keychain else self._password()
                )
                completed = subprocess.run(
                    command,
                    cwd=str(self.settings.project_root),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.enhancv_timeout_seconds,
                    check=False,
                )
                payload = self._compact_report(
                    json_out,
                    text_out,
                    completed.returncode,
                    self._redact_external_output(completed.stderr),
                    result,
                )

            final_path = workspace / "reports" / "enhancv-final.json"
            final_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            final_path.chmod(0o600)
            status = "complete" if payload["ok"] else "failed"
            self.database.execute(
                """
                UPDATE external_ats_reports
                SET status = ?, score = ?, report_json = ?, artifact_path = ?,
                    error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    status,
                    payload.get("score"),
                    json_dumps(payload),
                    str(final_path),
                    payload.get("error"),
                    report_id,
                ),
            )
        except subprocess.TimeoutExpired:
            self._fail(report_id, "Enhancv did not finish within the configured timeout")
        except Exception as exc:  # the persisted status is the user-facing boundary
            self._fail(report_id, self._safe_error(str(exc)))

    def latest(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = self.database.fetch_one(
            """
            SELECT * FROM external_ats_reports
            WHERE run_id = ? AND engine = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (run_id, self.ENGINE),
        )
        return self._public(row) if row else None

    def get(self, report_id: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM external_ats_reports WHERE id = ?", (report_id,)
        )
        if not row:
            raise KeyError("Enhancv report not found")
        return self._public(row)

    def _run(self, run_id: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM resume_runs WHERE id = ?", (run_id,)
        )
        if not row:
            raise KeyError("Resume run not found")
        result = {}
        if row.get("result_path") and Path(row["result_path"]).is_file():
            result = json.loads(Path(row["result_path"]).read_text(encoding="utf-8"))
        row["result_json"] = json_dumps(result)
        return row

    def _script_path(self) -> Optional[Path]:
        if not self.settings.enhancv_script_path:
            return None
        configured = self.settings.enhancv_script_path.expanduser()
        if configured.is_symlink():
            return None
        path = configured.resolve()
        if path.suffix != ".py":
            return None
        return path

    def _password(self) -> str:
        value = self.settings.enhancv_password
        return value.get_secret_value() if isinstance(value, SecretStr) else ""

    @staticmethod
    def _binding(result: Dict[str, Any]) -> tuple[int, str, str]:
        variant = result.get("variant")
        provenance = result.get("provenance", {})
        pdf_hash = provenance.get("pdf_hash")
        jd_hash = provenance.get("job_snapshot_hash")
        if (
            not isinstance(variant, int)
            or variant < 1
            or not pdf_hash
            or not jd_hash
        ):
            raise EnhancvUnavailable(
                "The current resume has no verifiable resume and job-description binding"
            )
        return variant, str(pdf_hash), str(jd_hash)

    @staticmethod
    def _keychain_configured(email: str) -> bool:
        security_path = shutil.which("security") if sys.platform == "darwin" else None
        if not email or not security_path:
            return False
        result = subprocess.run(
            [
                security_path,
                "find-generic-password",
                "-s",
                "enhancv.com",
                "-a",
                email,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0

    @staticmethod
    def _confined_file(workspace: Path, value: Any, label: str) -> Path:
        configured = Path(value).expanduser()
        if configured.is_symlink():
            raise EnhancvUnavailable(f"The {label} is unavailable")
        path = configured.resolve()
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise EnhancvUnavailable(f"The {label} escapes the resume workspace") from exc
        if not path.is_file() or path.is_symlink():
            raise EnhancvUnavailable(f"The {label} is unavailable")
        return path

    def _redact_external_output(self, value: str) -> str:
        redacted = value
        for secret in (self._password(), (self.settings.enhancv_email or "").strip()):
            if secret:
                redacted = redacted.replace(secret, "[redacted]")
        return redacted

    def _redact_external_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_external_output(value)
        if isinstance(value, dict):
            return {
                self._redact_external_output(str(key)): self._redact_external_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._redact_external_value(item) for item in value]
        return value

    def _compact_report(
        self,
        json_path: Path,
        text_path: Path,
        return_code: int,
        stderr: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        raw = {}
        if json_path.is_file():
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = {}
        report_text = self._redact_external_output(
            text_path.read_text(encoding="utf-8", errors="replace")[:120_000]
            if text_path.is_file()
            else ""
        )
        ok = bool(raw.get("ok")) and return_code == 0
        score = raw.get("tailoredScore") if raw.get("mode") == "jd-tailored" else raw.get("score")
        blocker = self._redact_external_output(str(raw.get("blocker") or "")) or None
        error = None if ok else self._safe_error(
            str(blocker or stderr or f"checker exited with {return_code}")
        )
        return {
            "engine": self.ENGINE,
            "provider": "Enhancv",
            "external": True,
            "ok": ok,
            "mode": raw.get("mode") or "jd-tailored",
            "score": score if isinstance(score, (int, float)) else None,
            "sections": self._redact_external_value(raw.get("sections"))
            if isinstance(raw.get("sections"), dict)
            else {},
            "tailoring": self._redact_external_value(raw.get("tailoring"))
            if isinstance(raw.get("tailoring"), dict)
            else {},
            "generic_score": raw.get("genericScore"),
            "blocker": blocker,
            "captcha_detected": bool(raw.get("captchaDetected")),
            "report_text": report_text,
            "resume_pdf_hash": result.get("provenance", {}).get("pdf_hash"),
            "job_description_hash": result.get("provenance", {}).get("job_snapshot_hash"),
            "error": error,
            "disclaimer": (
                "External diagnostic supplied by Enhancv. Carivyo does not alter, "
                "round, or treat this score as permission to add unsupported claims."
            ),
        }

    @staticmethod
    def _safe_error(value: str) -> str:
        cleaned = " ".join(value.split())
        return cleaned[:800] or "Enhancv report failed"

    def _fail(self, report_id: str, error: str) -> None:
        safe_error = self._safe_error(self._redact_external_output(error))
        self.database.execute(
            """
            UPDATE external_ats_reports
            SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (safe_error, report_id),
        )

    @staticmethod
    def _public(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "variant": row["variant"],
            "resume_pdf_hash": row["resume_pdf_hash"],
            "job_description_hash": row["job_description_hash"],
            "engine": row["engine"],
            "status": row["status"],
            "score": row.get("score"),
            "report": json_loads(row.get("report_json"), {}),
            "error": row.get("error"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
