from __future__ import annotations

import json

import structlog

from app.core.logging import bind_request_context, clear_request_context, configure_logging


def test_structlog_injects_correlation_id(capsys) -> None:
    configure_logging("info")
    clear_request_context()
    bind_request_context(correlation_id="corr-123")

    structlog.get_logger("test").info("log-event")

    clear_request_context()
    payload = capsys.readouterr().out.strip()
    log_line = json.loads(payload)
    assert log_line["correlation_id"] == "corr-123"
    assert log_line["event"] == "log-event"


def test_structlog_injects_trace_context(monkeypatch, capsys) -> None:
    from app.core import logging as logging_module

    class FakeSpanContext:
        is_valid = True
        trace_id = int("1" * 32, 16)
        span_id = int("2" * 16, 16)

    class FakeSpan:
        @staticmethod
        def get_span_context() -> FakeSpanContext:
            return FakeSpanContext()

    configure_logging("info")
    clear_request_context()
    monkeypatch.setattr(logging_module.trace, "get_current_span", lambda: FakeSpan())

    structlog.get_logger("test").info("trace-log")

    payload = capsys.readouterr().out.strip()
    log_line = json.loads(payload)
    assert log_line["trace_id"] == "1" * 32
    assert log_line["span_id"] == "2" * 16


def test_structlog_redacts_nested_sensitive_fields(capsys) -> None:
    configure_logging("info")
    clear_request_context()

    structlog.get_logger("test").info(
        "nested-secret",
        payload={"headers": {"authorization": "Bearer secret-token"}},
    )

    payload = capsys.readouterr().out.strip()
    log_line = json.loads(payload)
    assert log_line["payload"]["headers"]["authorization"] == "[REDACTED]"
