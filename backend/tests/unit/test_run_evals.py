from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest


def _make_args() -> argparse.Namespace:
    return argparse.Namespace(
        base_url=None,
        admin_key=None,
        dataset=None,
        tags=None,
        top_n=None,
        output_dir=None,
        snapshot_id=None,
        judge_model=None,
        persona_path=None,
    )


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        base_url="http://localhost:8000",
        admin_key="test-admin-key",
        top_n=5,
        output_dir="evals/reports",
        snapshot_id=None,
        judge_model=None,
        persona_path="persona/",
        seed_persona_path="evals/seed_persona/",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FileNotFoundError("missing dataset"), "Dataset loading failed: missing dataset"),
        (ValueError("invalid dataset"), "Dataset loading failed: invalid dataset"),
    ],
)
async def test_main_returns_error_when_dataset_loading_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected: str,
) -> None:
    from evals import run_evals

    monkeypatch.setattr(run_evals, "parse_args", lambda argv=None: _make_args())
    monkeypatch.setattr(run_evals.EvalConfig, "from_env", lambda **_: _make_config())

    def raise_error(*args: object, **kwargs: object) -> list[object]:
        raise error

    monkeypatch.setattr(run_evals, "load_datasets", raise_error)

    exit_code = await run_evals.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert expected in captured.err


def test_resolve_persona_path_falls_back_to_seed_fixture(tmp_path: Path) -> None:
    from evals import run_evals

    runtime_persona = tmp_path / "persona"
    seed_persona = tmp_path / "seed_persona"
    runtime_persona.mkdir()
    seed_persona.mkdir()
    for name in ("IDENTITY.md", "SOUL.md", "BEHAVIOR.md"):
        (seed_persona / name).write_text(name, encoding="utf-8")

    config = SimpleNamespace(
        persona_path=str(runtime_persona),
        seed_persona_path=str(seed_persona),
    )

    resolved = run_evals._resolve_persona_path(config, persona_path_explicit=False)

    assert resolved == seed_persona


def test_resolve_persona_path_keeps_explicit_runtime_path(tmp_path: Path) -> None:
    from evals import run_evals

    runtime_persona = tmp_path / "persona"
    runtime_persona.mkdir()
    config = SimpleNamespace(
        persona_path=str(runtime_persona),
        seed_persona_path=str(tmp_path / "seed_persona"),
    )

    resolved = run_evals._resolve_persona_path(config, persona_path_explicit=True)

    assert resolved == runtime_persona


@pytest.mark.asyncio
async def test_main_returns_error_when_answer_scoring_has_no_judge_model(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from evals import run_evals

    monkeypatch.setattr(run_evals, "parse_args", lambda argv=None: _make_args())
    monkeypatch.setattr(run_evals.EvalConfig, "from_env", lambda **_: _make_config())
    monkeypatch.setattr(
        run_evals,
        "load_datasets",
        lambda *args, **kwargs: [
            SimpleNamespace(
                suite="answer_quality",
                cases=[SimpleNamespace(answer_expectations=SimpleNamespace(), id="a-001")],
            )
        ],
    )
    monkeypatch.delenv("LLM_MODEL", raising=False)

    exit_code = await run_evals.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Answer-quality evals require EVAL_JUDGE_MODEL or LLM_MODEL" in captured.err
