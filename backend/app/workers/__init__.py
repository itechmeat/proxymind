from __future__ import annotations

from typing import Any

__all__ = ["WorkerSettings"]


def __getattr__(name: str) -> Any:
    if name == "WorkerSettings":
        from app.workers.main import WorkerSettings

        return WorkerSettings
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
