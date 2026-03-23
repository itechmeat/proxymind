from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class PersonaContext:
    identity: str
    soul: str
    behavior: str
    config_commit_hash: str
    config_content_hash: str


class PersonaLoader:
    def __init__(self, *, persona_dir: Path, config_dir: Path) -> None:
        self._persona_dir = persona_dir
        self._config_dir = config_dir

    def load(self) -> PersonaContext:
        identity = self._read_persona_file("IDENTITY.md")
        soul = self._read_persona_file("SOUL.md")
        behavior = self._read_persona_file("BEHAVIOR.md")
        config_commit_hash = self._resolve_commit_hash()
        config_content_hash = self._compute_content_hash()

        logger.info(
            "persona.loaded",
            config_commit_hash=config_commit_hash,
            config_content_hash=config_content_hash,
        )

        return PersonaContext(
            identity=identity,
            soul=soul,
            behavior=behavior,
            config_commit_hash=config_commit_hash,
            config_content_hash=config_content_hash,
        )

    def _read_persona_file(self, file_name: str) -> str:
        file_path = self._persona_dir / file_name
        try:
            return file_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning("persona.file_missing", file_name=file_name, path=str(file_path))
            return ""

    def _compute_content_hash(self) -> str:
        digest = hashlib.sha256()

        for relative_path, file_bytes in self._iter_hash_entries():
            digest.update(relative_path.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(file_bytes)

        return digest.hexdigest()

    def _iter_hash_entries(self) -> list[tuple[str, bytes]]:
        entries: list[tuple[str, bytes]] = []

        for directory in (self._persona_dir, self._config_dir):
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                relative_path = str(path.relative_to(directory.parent))
                entries.append((relative_path, path.read_bytes()))

        entries.sort(key=lambda entry: entry[0])
        return entries

    @staticmethod
    def _resolve_commit_hash() -> str:
        env_value = os.environ.get("GIT_COMMIT_SHA")
        if env_value:
            return env_value.strip()

        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "unknown"

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return "unknown"
