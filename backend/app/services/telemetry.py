from __future__ import annotations

from urllib.parse import urlparse

import structlog
from collections.abc import Mapping

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings

logger = structlog.get_logger(__name__)
_provider: TracerProvider | None = None
_httpx_instrumented = False
_redis_instrumented = False
_fastapi_apps: dict[int, FastAPI] = {}
_sqlalchemy_engines: dict[int, AsyncEngine] = {}


def _normalize_otlp_grpc_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme and parsed.netloc and parsed.path in {"", "/"}:
        return parsed.netloc
    return endpoint


def init_telemetry(settings: Settings, *, service_name: str | None = None) -> None:
    if not settings.otel_enabled:
        return

    global _provider, _httpx_instrumented, _redis_instrumented
    if _provider is None:
        resource_attributes: Mapping[str, str] = {
            "service.name": service_name or settings.otel_service_name,
            "deployment.environment": settings.otel_environment,
        }
        provider = TracerProvider(resource=Resource.create(resource_attributes))
        exporter = OTLPSpanExporter(
            endpoint=_normalize_otlp_grpc_endpoint(settings.otel_exporter_otlp_endpoint),
            insecure=True,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider = provider

    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument()
        _httpx_instrumented = True
    if not _redis_instrumented:
        RedisInstrumentor().instrument()
        _redis_instrumented = True


def instrument_fastapi(app: FastAPI) -> None:
    if _provider is None:
        return
    app_key = id(app)
    if app_key in _fastapi_apps:
        return

    FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)
    _fastapi_apps[app_key] = app


def instrument_sqlalchemy(engine: AsyncEngine) -> None:
    if _provider is None:
        return
    engine_key = id(engine.sync_engine)
    if engine_key in _sqlalchemy_engines:
        return

    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        tracer_provider=_provider,
    )
    _sqlalchemy_engines[engine_key] = engine


def shutdown_telemetry() -> None:
    global _provider, _httpx_instrumented, _redis_instrumented
    if _provider is None:
        return

    for app in list(_fastapi_apps.values()):
        try:
            FastAPIInstrumentor().uninstrument_app(app)
        except Exception as error:
            logger.warning("telemetry.fastapi_uninstrument_failed", error=str(error))

    for engine in list(_sqlalchemy_engines.values()):
        try:
            SQLAlchemyInstrumentor().uninstrument(engine=engine.sync_engine)
        except Exception as error:
            logger.warning("telemetry.sqlalchemy_uninstrument_failed", error=str(error))

    if _httpx_instrumented:
        try:
            HTTPXClientInstrumentor().uninstrument()
        except Exception as error:
            logger.warning("telemetry.httpx_uninstrument_failed", error=str(error))

    if _redis_instrumented:
        try:
            RedisInstrumentor().uninstrument()
        except Exception as error:
            logger.warning("telemetry.redis_uninstrument_failed", error=str(error))

    try:
        _provider.force_flush()
        _provider.shutdown()
    finally:
        _provider = None
        _httpx_instrumented = False
        _redis_instrumented = False
        _fastapi_apps.clear()
        _sqlalchemy_engines.clear()


__all__ = [
    "init_telemetry",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "shutdown_telemetry",
]
