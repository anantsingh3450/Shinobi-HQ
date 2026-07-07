from __future__ import annotations

import hashlib
from pathlib import Path


class BrainFingerprinter:
    """Generates a deterministic hash representing the exact state of the brain files."""

    def __init__(self, brain_root: Path) -> None:
        self._brain_root = Path(brain_root).resolve()

    def compute_fingerprint(self) -> str:
        """Walk brain directory, ignore backups, hash file contents, and return checksum."""
        if not self._brain_root.exists():
            return ""

        file_hashes: list[tuple[str, str]] = []

        for path in sorted(self._brain_root.rglob("*")):
            if not path.is_file():
                continue

            rel_path = path.relative_to(self._brain_root)
            parts = rel_path.parts
            
            if "backups" in parts or "brain.json" in parts:
                continue

            file_hash = self._hash_file(path)
            file_hashes.append((rel_path.as_posix(), file_hash))

        file_hashes.sort(key=lambda x: x[0])

        hasher = hashlib.sha256()
        for rel_path_str, f_hash in file_hashes:
            hasher.update(rel_path_str.encode("utf-8"))
            hasher.update(f_hash.encode("utf-8"))

        return hasher.hexdigest()

    @staticmethod
    def _hash_file(filepath: Path) -> str:
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
