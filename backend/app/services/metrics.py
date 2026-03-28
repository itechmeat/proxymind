from __future__ import annotations

import re

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

_UUID_SEGMENT_RE = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?=/|$)"
)
_HTTP_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
_CHAT_LATENCY_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests processed by the API.",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    buckets=_HTTP_LATENCY_BUCKETS,
)
CHAT_RESPONSES_TOTAL = Counter(
    "chat_responses_total",
    "Total number of chat responses by terminal status.",
    ["status"],
)
CHAT_RESPONSE_LATENCY_SECONDS = Histogram(
    "chat_response_latency_seconds",
    "Chat response latency in seconds.",
    buckets=_CHAT_LATENCY_BUCKETS,
)
RATE_LIMIT_HITS_TOTAL = Counter(
    "rate_limit_hits_total",
    "Number of requests rejected by rate limiting.",
)
AUDIT_LOGS_TOTAL = Counter(
    "audit_logs_total",
    "Total number of audit log records written.",
)
BACKGROUND_JOB_COUNT = Counter(
    "background_jobs_total",
    "Total number of background jobs by task name and final status.",
    ["task_name", "status"],
)
BACKGROUND_JOB_DURATION = Histogram(
    "background_job_duration_seconds",
    "Background job duration in seconds by task name and final status.",
    ["task_name", "status"],
)
ARQ_QUEUE_DEPTH = Gauge(
    "arq_queue_depth",
    "Current number of jobs waiting in the default arq queue.",
)


def record_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    normalized_path = _normalize_path(path)
    HTTP_REQUESTS_TOTAL.labels(
        method=method,
        path=normalized_path,
        status_code=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=normalized_path).observe(
        duration_seconds
    )


def _normalize_path(path: str) -> str:
    return _UUID_SEGMENT_RE.sub("/:id", path)


def render_metrics() -> bytes:
    return generate_latest()


REQUEST_COUNT = HTTP_REQUESTS_TOTAL
REQUEST_LATENCY = HTTP_REQUEST_DURATION_SECONDS
CHAT_RESPONSE_COUNT = CHAT_RESPONSES_TOTAL
CHAT_RESPONSE_LATENCY = CHAT_RESPONSE_LATENCY_SECONDS
RATE_LIMIT_COUNT = RATE_LIMIT_HITS_TOTAL
AUDIT_LOG_COUNT = AUDIT_LOGS_TOTAL


__all__ = [
    "AUDIT_LOG_COUNT",
    "AUDIT_LOGS_TOTAL",
    "ARQ_QUEUE_DEPTH",
    "BACKGROUND_JOB_COUNT",
    "BACKGROUND_JOB_DURATION",
    "CHAT_RESPONSE_COUNT",
    "CHAT_RESPONSE_LATENCY",
    "CHAT_RESPONSE_LATENCY_SECONDS",
    "CHAT_RESPONSES_TOTAL",
    "CONTENT_TYPE_LATEST",
    "HTTP_REQUEST_DURATION_SECONDS",
    "HTTP_REQUESTS_TOTAL",
    "RATE_LIMIT_COUNT",
    "RATE_LIMIT_HITS_TOTAL",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "_normalize_path",
    "record_request",
    "render_metrics",
]
