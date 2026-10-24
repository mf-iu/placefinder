"""OpenTelemetry (telemetry.py): off without an endpoint; with one, spans and
the request duration per route. The exporters are replaced by in-memory ones,
and the global providers are not touched, so other tests stay unaffected."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from placefinder import cache, telemetry
from placefinder.cache import SearchCache


def metric_points(reader: InMemoryMetricReader) -> dict[str, list]:
    data = reader.get_metrics_data()
    return {
        m.name: list(m.data.data_points)
        for rm in (data.resource_metrics if data else [])
        for sm in rm.scope_metrics
        for m in sm.metrics
    }


def test_off_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert telemetry.setup(FastAPI()) is False


def test_off_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert telemetry.setup(FastAPI()) is False


def test_spans_and_request_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda: spans)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", SimpleSpanProcessor)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", lambda: None)
    monkeypatch.setattr(telemetry, "PeriodicExportingMetricReader", lambda exporter: reader)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)
    monkeypatch.setattr(telemetry.metrics, "set_meter_provider", lambda provider: None)
    monkeypatch.setattr(
        telemetry,
        "PsycopgInstrumentor",
        lambda: type("NoPsycopg", (), {"instrument": lambda self, **kwargs: None})(),
    )

    app = FastAPI()

    @app.get("/v1/places/{place_id}")
    def place(place_id: int) -> dict[str, int]:
        return {"id": place_id}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/livez")
    def livez() -> dict[str, str]:
        return {"status": "ok"}

    assert telemetry.setup(app) is True
    client = TestClient(app)
    client.get("/v1/places/2929670")
    client.get("/health")
    client.get("/livez")

    # one span per request, none for the health checks
    assert [s.name for s in spans.get_finished_spans()] == ["GET /v1/places/{place_id}"]
    span = spans.get_finished_spans()[0]
    assert span.resource.attributes["service.name"] == "placefinder"
    points = metric_points(reader)["http.server.request.duration"]
    assert [
        (p.attributes["http.route"], p.attributes["http.response.status_code"], p.count)
        for p in points
    ] == [("/v1/places/{place_id}", 200, 1)]


class FakeValkey:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int) -> None:
        self.data[key] = value


def test_cache_lookups_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = InMemoryMetricReader()
    counter = MeterProvider(metric_readers=[reader]).get_meter("test").create_counter("lookups")
    monkeypatch.setattr(cache, "LOOKUPS", counter)
    search_cache = SearchCache("valkey://localhost:6379/0", client=FakeValkey())
    search_cache.get("a")
    search_cache.put("a", {"body": {}})
    search_cache.get("a")
    search_cache.get("a")
    counts = {p.attributes["cache.result"]: p.value for p in metric_points(reader)["lookups"]}
    assert counts == {"miss": 1, "hit": 2}
