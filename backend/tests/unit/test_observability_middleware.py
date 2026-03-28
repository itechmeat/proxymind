from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from prometheus_client.parser import text_string_to_metric_families
from starlette.types import Receive, Scope, Send

from app.middleware.observability import ObservabilityMiddleware
from app.services.metrics import render_metrics


@pytest_asyncio.fixture
async def observability_client() -> httpx.AsyncClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(ObservabilityMiddleware)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_observability_middleware_generates_request_id(
    observability_client: httpx.AsyncClient,
) -> None:
    response = await observability_client.get("/ping")

    assert response.status_code == 200
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_observability_middleware_preserves_request_id(
    observability_client: httpx.AsyncClient,
) -> None:
    response = await observability_client.get(
        "/ping",
        headers={"X-Request-ID": "external-request-id"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "external-request-id"


@pytest.mark.asyncio
async def test_observability_middleware_passthrough_for_non_http() -> None:
    called = False

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    middleware = ObservabilityMiddleware(downstream)
    scope: Scope = {"type": "websocket", "path": "/ws", "headers": []}

    async def receive() -> dict[str, str]:
        return {"type": "websocket.disconnect"}

    async def send(_message: dict[str, str]) -> None:
        return None

    await middleware(scope, receive, send)

    assert called is True


@pytest.mark.asyncio
async def test_observability_middleware_records_route_template(
    observability_client: httpx.AsyncClient,
) -> None:
    await observability_client.get("/ping")

    request_samples = []
    for family in text_string_to_metric_families(render_metrics().decode("utf-8")):
        if family.name != "http_requests":
            continue
        request_samples.extend(family.samples)

    assert any(sample.labels.get("path") == "/ping" for sample in request_samples)


@pytest.mark.asyncio
async def test_observability_middleware_preserves_latin1_request_id() -> None:
    response_headers: list[tuple[bytes, bytes]] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"status":"ok"}',
                "more_body": False,
            }
        )

    middleware = ObservabilityMiddleware(downstream)
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/ping",
        "headers": [(b"x-request-id", "caf\xe9".encode("latin-1"))],
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            response_headers.extend(message.get("headers", []))

    await middleware(scope, receive, send)

    assert (b"x-request-id", "caf\xe9".encode("latin-1")) in response_headers
