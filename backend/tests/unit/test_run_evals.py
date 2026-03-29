from __future__ import annotations

import argparse
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
    )


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        base_url="http://localhost:8000",
        admin_key="test-admin-key",
        top_n=5,
        output_dir="evals/reports",
        snapshot_id=None,
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
