from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client.parser import text_string_to_metric_families

from app.api.metrics import router as metrics_router
from app.services.metrics import CONTENT_TYPE_LATEST, _normalize_path, record_request, render_metrics


def test_normalize_path_replaces_uuid_segments() -> None:
    normalized = _normalize_path(
        "/api/chat/sessions/123e4567-e89b-12d3-a456-426614174000/messages"
    )

    assert normalized == "/api/chat/sessions/:id/messages"


def test_render_metrics_contains_recorded_http_metric() -> None:
    record_request("GET", "/api/chat/sessions/123e4567-e89b-12d3-a456-426614174000", 200, 0.25)

    payload = render_metrics().decode("utf-8")

    assert "http_requests_total" in payload
    assert "/api/chat/sessions/:id" in payload


def test_http_request_metric_uses_status_code_label() -> None:
    record_request("POST", "/api/chat/messages", 429, 0.1)

    samples = []
    for family in text_string_to_metric_families(render_metrics().decode("utf-8")):
        if family.name != "http_requests":
            continue
        samples.extend(family.samples)

    assert any(sample.labels.get("status_code") == "429" for sample in samples)


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_payload_for_private_client() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(admin_api_key=None)
    app.include_router(metrics_router)

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(CONTENT_TYPE_LATEST)
    assert "http_requests_total" in response.text


@pytest.mark.asyncio
async def test_metrics_endpoint_rejects_public_client_without_auth() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(admin_api_key=None)
    app.include_router(metrics_router)

    transport = httpx.ASGITransport(app=app, client=("8.8.8.8", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 403
