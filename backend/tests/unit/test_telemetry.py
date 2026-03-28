from __future__ import annotations

from types import SimpleNamespace

from app.services import telemetry


def test_init_telemetry_disabled_is_noop() -> None:
    telemetry._provider = None
    telemetry._httpx_instrumented = False
    telemetry._redis_instrumented = False
    telemetry._telemetry_shutdown = False
    telemetry._fastapi_apps.clear()
    telemetry._sqlalchemy_engines.clear()

    telemetry.init_telemetry(SimpleNamespace(otel_enabled=False), service_name="test")

    assert telemetry._provider is None


def test_instrument_helpers_are_noop_without_provider() -> None:
    telemetry._provider = None
    telemetry._telemetry_shutdown = False
    app = object()
    engine = SimpleNamespace(sync_engine=object())

    telemetry.instrument_fastapi(app)  # type: ignore[arg-type]
    telemetry.instrument_sqlalchemy(engine)  # type: ignore[arg-type]

    assert not telemetry._fastapi_apps or id(app) not in telemetry._fastapi_apps
    assert not telemetry._sqlalchemy_engines or id(engine.sync_engine) not in telemetry._sqlalchemy_engines


def test_init_and_shutdown_telemetry(monkeypatch) -> None:
    telemetry._provider = None
    telemetry._httpx_instrumented = False
    telemetry._redis_instrumented = False
    telemetry._telemetry_shutdown = False
    telemetry._fastapi_apps.clear()
    telemetry._sqlalchemy_engines.clear()

    provider = SimpleNamespace(
        add_span_processor=lambda *_args, **_kwargs: None,
        force_flush=lambda: None,
        shutdown=lambda: None,
    )
    exporter = object()
    batch_processor = object()
    httpx_instrumentor = SimpleNamespace(instrument=lambda: None, uninstrument=lambda: None)
    redis_instrumentor = SimpleNamespace(instrument=lambda: None, uninstrument=lambda: None)
    fastapi_instrumentor = SimpleNamespace(
        instrument_app=lambda *_args, **_kwargs: None,
        uninstrument_app=lambda *_args, **_kwargs: None,
    )
    sqlalchemy_instrumentor = SimpleNamespace(
        instrument=lambda *_args, **_kwargs: None,
        uninstrument=lambda *_args, **_kwargs: None,
    )

    exporter_kwargs: dict[str, object] = {}

    monkeypatch.setattr(telemetry, "TracerProvider", lambda resource=None: provider)
    monkeypatch.setattr(
        telemetry,
        "OTLPSpanExporter",
        lambda endpoint=None, insecure=None: exporter_kwargs.update(
            endpoint=endpoint,
            insecure=insecure,
        )
        or exporter,
    )
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", lambda exporter_arg: batch_processor)
    monkeypatch.setattr(telemetry, "HTTPXClientInstrumentor", lambda: httpx_instrumentor)
    monkeypatch.setattr(telemetry, "RedisInstrumentor", lambda: redis_instrumentor)
    monkeypatch.setattr(telemetry, "FastAPIInstrumentor", fastapi_instrumentor)
    monkeypatch.setattr(telemetry, "SQLAlchemyInstrumentor", lambda: sqlalchemy_instrumentor)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda _provider: None)

    telemetry.init_telemetry(
        SimpleNamespace(
            otel_enabled=True,
            otel_service_name="proxymind-api",
            otel_environment="test",
            otel_exporter_otlp_endpoint="http://tempo:4317",
        ),
        service_name="proxymind-test",
    )

    assert telemetry._provider is provider
    assert exporter_kwargs == {
        "endpoint": "tempo:4317",
        "insecure": True,
    }

    telemetry.shutdown_telemetry()

    assert telemetry._provider is provider
    assert telemetry._httpx_instrumented is False
    assert telemetry._redis_instrumented is False
    assert telemetry._telemetry_shutdown is True


def test_init_telemetry_after_shutdown_is_ignored(monkeypatch) -> None:
    telemetry._provider = SimpleNamespace(force_flush=lambda: None, shutdown=lambda: None)
    telemetry._httpx_instrumented = False
    telemetry._redis_instrumented = False
    telemetry._telemetry_shutdown = True
    telemetry._fastapi_apps.clear()
    telemetry._sqlalchemy_engines.clear()

    set_provider = SimpleNamespace(call_count=0)

    def _set_tracer_provider(_provider) -> None:
        set_provider.call_count += 1

    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", _set_tracer_provider)

    telemetry.init_telemetry(
        SimpleNamespace(
            otel_enabled=True,
            otel_service_name="proxymind-api",
            otel_environment="test",
            otel_exporter_otlp_endpoint="http://tempo:4317",
        )
    )

    assert set_provider.call_count == 0


def test_normalize_otlp_grpc_endpoint_strips_scheme() -> None:
    assert telemetry._normalize_otlp_grpc_endpoint("http://tempo:4317") == "tempo:4317"
    assert telemetry._normalize_otlp_grpc_endpoint("tempo:4317") == "tempo:4317"
