from __future__ import annotations

import hashlib
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.persona.loader import PersonaContext, PersonaLoader


@pytest.fixture
def persona_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "persona"
    directory.mkdir()
    return directory


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    return directory


def _write(directory: Path, name: str, content: str) -> None:
    (directory / name).write_text(content, encoding="utf-8")


def test_loads_all_persona_fields(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "I am the twin.")
    _write(persona_dir, "SOUL.md", "I speak calmly.")
    _write(persona_dir, "BEHAVIOR.md", "I avoid politics.")

    context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert context.identity == "I am the twin."
    assert context.soul == "I speak calmly."
    assert context.behavior == "I avoid politics."
    assert len(context.config_commit_hash) > 0
    assert len(context.config_content_hash) == 64


def test_missing_one_file_returns_empty_string(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "present")
    _write(persona_dir, "BEHAVIOR.md", "present")

    context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert context.identity == "present"
    assert context.soul == ""
    assert context.behavior == "present"


def test_empty_files_return_empty_strings(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "")
    _write(persona_dir, "SOUL.md", "  \n")
    _write(persona_dir, "BEHAVIOR.md", "value")

    context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert context.identity == ""
    assert context.soul == ""
    assert context.behavior == "value"


def test_missing_persona_dir_returns_empty_strings(tmp_path: Path, config_dir: Path) -> None:
    missing_dir = tmp_path / "missing-persona"

    context = PersonaLoader(persona_dir=missing_dir, config_dir=config_dir).load()

    assert context.identity == ""
    assert context.soul == ""
    assert context.behavior == ""


def test_hash_is_deterministic(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "same")
    _write(persona_dir, "SOUL.md", "same")
    _write(persona_dir, "BEHAVIOR.md", "same")

    loader = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir)

    assert loader.load().config_content_hash == loader.load().config_content_hash


def test_hash_changes_when_persona_changes(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "v1")
    _write(persona_dir, "SOUL.md", "")
    _write(persona_dir, "BEHAVIOR.md", "")

    loader = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir)
    first_hash = loader.load().config_content_hash
    _write(persona_dir, "IDENTITY.md", "v2")

    assert loader.load().config_content_hash != first_hash


def test_hash_includes_config_dir(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "value")
    _write(persona_dir, "SOUL.md", "value")
    _write(persona_dir, "BEHAVIOR.md", "value")

    loader = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir)
    first_hash = loader.load().config_content_hash
    _write(config_dir, "PROMOTIONS.md", "promo")

    assert loader.load().config_content_hash != first_hash


def test_empty_or_missing_dirs_produce_empty_hash(tmp_path: Path) -> None:
    missing_persona_dir = tmp_path / "persona"
    missing_config_dir = tmp_path / "config"

    context = PersonaLoader(
        persona_dir=missing_persona_dir,
        config_dir=missing_config_dir,
    ).load()

    assert context.config_content_hash == hashlib.sha256(b"").hexdigest()


def test_uses_env_var_for_commit_hash(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "x")
    _write(persona_dir, "SOUL.md", "y")
    _write(persona_dir, "BEHAVIOR.md", "z")

    with patch.dict(os.environ, {"GIT_COMMIT_SHA": "abc123"}):
        context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert context.config_commit_hash == "abc123"


def test_falls_back_to_unknown_when_git_is_unavailable(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "x")
    _write(persona_dir, "SOUL.md", "y")
    _write(persona_dir, "BEHAVIOR.md", "z")

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("app.persona.loader.subprocess.run", side_effect=FileNotFoundError),
    ):
        context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert context.config_commit_hash == "unknown"


def test_falls_back_to_git_rev_parse_when_env_var_is_missing(
    persona_dir: Path,
    config_dir: Path,
) -> None:
    _write(persona_dir, "IDENTITY.md", "x")
    _write(persona_dir, "SOUL.md", "y")
    _write(persona_dir, "BEHAVIOR.md", "z")

    with (
        patch.dict(os.environ, {}, clear=True),
        patch(
            "app.persona.loader.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="git-sha\n"),
        ),
    ):
        context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert context.config_commit_hash == "git-sha"


def test_persona_context_is_frozen(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "x")
    _write(persona_dir, "SOUL.md", "y")
    _write(persona_dir, "BEHAVIOR.md", "z")

    context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    with pytest.raises(FrozenInstanceError):
        context.identity = "changed"  # type: ignore[misc]


def test_persona_context_has_expected_fields(persona_dir: Path, config_dir: Path) -> None:
    _write(persona_dir, "IDENTITY.md", "x")
    _write(persona_dir, "SOUL.md", "y")
    _write(persona_dir, "BEHAVIOR.md", "z")

    context = PersonaLoader(persona_dir=persona_dir, config_dir=config_dir).load()

    assert isinstance(context, PersonaContext)
    assert tuple(context.__dataclass_fields__) == (
        "identity",
        "soul",
        "behavior",
        "config_commit_hash",
        "config_content_hash",
    )
