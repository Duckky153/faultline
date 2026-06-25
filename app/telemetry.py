"""OpenTelemetry setup for the orders demo (plain-English version below).

Every request becomes a "trace": one parent span for the request, with child
spans for the database lookup and a downstream call. A *span* is one timed step;
a *trace* is the whole story of one request made of those steps.

If an OTLP endpoint is configured via the standard environment variables
(OTEL_EXPORTER_OTLP_ENDPOINT + OTEL_EXPORTER_OTLP_HEADERS), the very same spans
are shipped to that backend — e.g. a Dynatrace tenant — with no code change.
With nothing configured, the app still runs and traces locally; it just doesn't
send them anywhere.
"""
from __future__ import annotations

import os
import threading

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "orders-demo"
_configured = False
# configure() installs a process-global TracerProvider exactly once. Without a
# lock, two threads racing the first call could each build a provider and the
# second set_tracer_provider() would clobber the first (losing its exporter).
_configure_lock = threading.Lock()


def configure() -> TracerProvider:
    """Install a TracerProvider once; attach an OTLP exporter only if configured."""
    global _configured
    existing = trace.get_tracer_provider()
    if _configured and isinstance(existing, TracerProvider):
        return existing

    with _configure_lock:
        # Double-check inside the lock: another thread may have configured it
        # while we were waiting to acquire the lock.
        existing = trace.get_tracer_provider()
        if _configured and isinstance(existing, TracerProvider):
            return existing

        resource = Resource.create({"service.name": SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        # Ship spans to an OTLP backend (e.g. Dynatrace) ONLY when an endpoint is set.
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

        trace.set_tracer_provider(provider)
        _configured = True
        return provider


def get_tracer() -> trace.Tracer:
    configure()
    return trace.get_tracer(SERVICE_NAME)
