"""Traces and metrics with OpenTelemetry (from session 8).

Telemetry is off unless OTEL_EXPORTER_OTLP_ENDPOINT is set, e.g. to the
OpenTelemetry backend of compose.yaml: http://lgtm:4318. PlaceFinder then
sends both signals with OTLP over HTTP:

- Traces: one span per request (FastAPI) with a child span per SQL statement
  (psycopg), so a slow search shows where the time goes.
- Metrics: the request duration as a histogram per route and status code
  (http.server.request.duration, in Prometheus
  http_server_request_duration_seconds) - rate, errors and duration (RED)
  follow from it - and the cache lookups by result (cache.py).

All further settings come from the standard OTEL_* environment variables of
the SDK, e.g. OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES,
OTEL_METRIC_EXPORT_INTERVAL (milliseconds, default 60000) or
OTEL_TRACES_SAMPLER. The same code therefore sends to any backend that speaks
OTLP: Jaeger, Prometheus, Grafana, or the services of the cloud providers.
"""

import logging
import os
from importlib.metadata import version

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger("uvicorn.error")


def enabled() -> bool:
    return (
        bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
        and os.environ.get("OTEL_SDK_DISABLED", "false").lower() != "true"
    )


def setup(app: FastAPI) -> bool:
    """Instrument the app and start the exporters if an OTLP endpoint is set.
    Call it once, before the app serves the first request."""
    if not enabled():
        return False
    # stable names of the HTTP semantic conventions (http.server.request.duration
    # in seconds, http.response.status_code) instead of the old ones
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    # service.name from OTEL_SERVICE_NAME, otherwise placefinder
    resource = Resource.create(
        {SERVICE_NAME: "placefinder", SERVICE_VERSION: version("placefinder")}
        | ({SERVICE_NAME: name} if (name := os.environ.get("OTEL_SERVICE_NAME")) else {})
    )
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]
    )
    metrics.set_meter_provider(meter_provider)
    # health checks every few seconds would drown the real requests
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="health",
        exclude_spans=["receive", "send"],
    )
    PsycopgInstrumentor().instrument(tracer_provider=tracer_provider, skip_dep_check=True)
    logger.info(
        "Sending traces and metrics to %s as %s",
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
        resource.attributes[SERVICE_NAME],
    )
    return True
