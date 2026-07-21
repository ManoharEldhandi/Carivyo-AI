from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict

from app.config import Settings
from app.db import Database
from app.utils import utcnow


class BackupService:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database

    def create(self) -> Dict[str, Any]:
        timestamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        destination = self.settings.backups_dir / f"carivyo-{timestamp}.zip"
        with tempfile.TemporaryDirectory(prefix="carivyo-backup-") as temporary:
            temporary_path = Path(temporary)
            database_copy = temporary_path / "carivyo.sqlite3"
            self.database.backup_to(database_copy)
            manifest = {
                "format": 1,
                "created_at": utcnow().isoformat(),
                "files": {},
                "notes": "Session secrets and provider credentials are not included.",
            }
            files = [database_copy]
            if self.settings.artifacts_dir.exists():
                files.extend(
                    path
                    for path in self.settings.artifacts_dir.rglob("*")
                    if path.is_file()
                )
            with zipfile.ZipFile(
                destination,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as archive:
                for path in files:
                    if path == database_copy:
                        archive_name = "data/carivyo.sqlite3"
                    else:
                        archive_name = "data/artifacts/" + str(
                            path.relative_to(self.settings.artifacts_dir)
                        )
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    manifest["files"][archive_name] = {
                        "sha256": digest,
                        "size": path.stat().st_size,
                    }
                    archive.write(path, arcname=archive_name)
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                )
        destination.chmod(0o600)
        return {
            "path": str(destination.resolve()),
            "filename": destination.name,
            "size_bytes": destination.stat().st_size,
            "manifest": manifest,
        }
