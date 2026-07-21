from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Tuple


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactError(ValueError):
    pass


class ArtifactVault:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def confined(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ArtifactError("Path escapes the artifact vault")
        return resolved

    def directory(self, *parts: str) -> Path:
        target = self.confined(self.root.joinpath(*parts))
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.chmod(0o700)
        return target

    def store_upload(self, filename: str, content: bytes) -> Tuple[Path, str]:
        digest = hashlib.sha256(content).hexdigest()
        safe_name = SAFE_NAME.sub("-", Path(filename).name).strip(".-") or "upload"
        directory = self.directory("imports", digest)
        target = self.confined(directory / safe_name)
        if not target.exists():
            target.write_bytes(content)
            target.chmod(0o600)
        return target, digest

    def write_text(self, relative: str, content: str) -> Path:
        target = self.confined(self.root / relative)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_text(content, encoding="utf-8")
        target.chmod(0o600)
        return target

    def write_bytes(self, relative: str, content: bytes) -> Path:
        target = self.confined(self.root / relative)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(content)
        target.chmod(0o600)
        return target

    @staticmethod
    def hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def secure_delete(path: Path) -> None:
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            for child in path.iterdir():
                ArtifactVault.secure_delete(child)
            path.rmdir()

    @staticmethod
    def assert_not_symlink(path: Path) -> None:
        current = path
        while current != current.parent:
            if current.exists() and os.path.islink(current):
                raise ArtifactError("Symlink paths are not allowed")
            current = current.parent
