import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar

import structlog
from opentelemetry import trace

_REDACT_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api_key",
        "token",
        "password",
        "secret",
    }
)
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_context(**values: object) -> None:
    request_id = values.get("request_id")
    if isinstance(request_id, str):
        request_id_var.set(request_id)
    structlog.contextvars.bind_contextvars(**values)


def clear_request_context() -> None:
    request_id_var.set(None)
    structlog.contextvars.clear_contextvars()


def get_request_id() -> str | None:
    return request_id_var.get()


def _redact_value(value: object) -> object:
    if isinstance(value, MutableMapping):
        return {
            key: "[REDACTED]" if str(key).lower() in _REDACT_KEYS else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_sensitive_fields(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    redacted: structlog.typing.EventDict = {}
    for key, value in event_dict.items():
        if key.lower() in _REDACT_KEYS:
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = _redact_value(value)
    return redacted


def add_request_context(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def _add_trace_context(
    _logger: structlog.typing.WrappedLogger,
    _method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if span_context.is_valid:
        event_dict.setdefault("trace_id", format(span_context.trace_id, "032x"))
        event_dict.setdefault("span_id", format(span_context.span_id, "016x"))
    return event_dict


def configure_logging(level: str = "info") -> None:
    level_value = getattr(logging, level.upper())
    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_request_context,
        _add_trace_context,
        redact_sensitive_fields,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_value),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level_value,
        force=True,
    )
