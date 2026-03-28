from __future__ import annotations

import time
import uuid

import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import bind_request_context, clear_request_context
from app.services.metrics import record_request

logger = structlog.get_logger(__name__)
_REQUEST_ID_HEADER = b"x-request-id"


def _extract_request_id(scope: Scope) -> str | None:
    for header_name, header_value in scope.get("headers", []):
        if header_name.lower() == _REQUEST_ID_HEADER:
            return header_value.decode("latin-1")
    return None


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        path = scope["path"]
        request_id = _extract_request_id(scope) or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        bind_request_context(
            request_id=request_id,
            http_method=method,
            http_path=path,
        )

        status_code = 500
        started_at = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as error:
            current_span = trace.get_current_span()
            span_context = current_span.get_span_context()
            if span_context.is_valid:
                current_span.record_exception(error)
                current_span.set_status(Status(StatusCode.ERROR, str(error)))
            logger.exception(
                "http.request_failed",
                method=method,
                path=path,
            )
            raise
        finally:
            route_path = _resolve_route_path(scope) or path
            duration_seconds = time.perf_counter() - started_at
            current_span = trace.get_current_span()
            span_context = current_span.get_span_context()
            if span_context.is_valid:
                current_span.set_attribute("http.method", method)
                current_span.set_attribute("http.route", route_path)
                current_span.set_attribute("http.target", path)
                current_span.set_attribute("http.status_code", status_code)
                current_span.set_attribute("request_id", request_id)
                if status_code >= 500:
                    current_span.set_status(Status(StatusCode.ERROR))
            record_request(method, route_path, status_code, duration_seconds)
            logger.info(
                "http.request_completed",
                method=method,
                path=route_path,
                status_code=status_code,
                duration_ms=round(duration_seconds * 1000),
            )
            clear_request_context()


def _resolve_route_path(scope: Scope) -> str | None:
    route = scope.get("route")
    if not isinstance(route, BaseRoute):
        return None
    path_format = getattr(route, "path_format", None)
    if isinstance(path_format, str):
        return path_format
    path_value = getattr(route, "path", None)
    if isinstance(path_value, str):
        return path_value
    return None
