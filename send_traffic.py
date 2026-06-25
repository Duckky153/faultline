"""Generate demo traffic and flush the traces to Dynatrace.

Runs the app in-process, makes a mix of healthy / slow / failing requests
(so Dynatrace has something interesting to show), then force-flushes the
OpenTelemetry spans to whatever OTLP backend is configured in the environment.
"""
from __future__ import annotations

import os
from pathlib import Path

# Load .env (KEY=VALUE, tolerating an 'export ' prefix + quotes) BEFORE importing
# the app, so the OpenTelemetry exporter is configured at import time.
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#"):
            continue
        if _line.startswith("export "):
            _line = _line[len("export ") :]
        if "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import logging

from fastapi.testclient import TestClient
from opentelemetry import trace

from app import store
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


class _ExportFailureWatcher(logging.Handler):
    """force_flush() reports only whether the queue drained, not whether the
    backend accepted the spans — the OTLP HTTP exporter logs an error and
    returns instead of raising. So we also watch the SDK's export logger and
    treat any logged export error as a failed delivery, so the demo can't
    falsely claim success when spans never reached Dynatrace."""

    failed = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            type(self).failed = True


_export_watcher = _ExportFailureWatcher()
logging.getLogger("opentelemetry.sdk.trace.export").addHandler(_export_watcher)
logging.getLogger("opentelemetry.exporter.otlp").addHandler(_export_watcher)

# With no OTLP endpoint configured, there's nowhere to ship spans — so print
# them to the console instead, so running this script still visibly produces
# traces. (This lives only in send_traffic.py, never in the app or tests, so it
# can't add noise to the test run.)
if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )

    _provider = trace.get_tracer_provider()
    if isinstance(_provider, TracerProvider):
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    print("(no OTLP endpoint set — printing spans to the console instead)\n")


def burst(label: str, n: int) -> None:
    print(f"-- {label} --")
    for i in range(n):
        oid = (i % 3) + 1
        r = client.get(f"/orders/{oid}")
        print(f"  GET /orders/{oid} -> {r.status_code}")


# A realistic mix so the trace/service view has signal.
store.set_fault("none")
burst("healthy", 10)
store.set_fault("slow")
burst("slow database", 5)
store.set_fault("error")
burst("failing database", 6)
store.set_fault("none")
burst("recovered", 4)


def _redacted_endpoint() -> str:
    """Where spans are being shipped, with any token in the headers redacted."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or "(none configured)"
    headers = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")
    # Redact the Api-Token value so a copied terminal log never leaks the token.
    if "Api-Token" in headers:
        endpoint += "  (Authorization=Api-Token <redacted>)"
    return endpoint


# Push everything to Dynatrace now (don't wait for the batch timer).
provider = trace.get_tracer_provider()
try:
    # force_flush() returns True only if every span drained before the timeout.
    flushed = provider.force_flush()
finally:
    # Always release the exporter/batch processor cleanly, even on failure.
    provider.shutdown()

# Success = the queue drained AND no export error was logged along the way.
flushed = bool(flushed) and not _ExportFailureWatcher.failed

if flushed:
    print(f"\nflushed all spans to {_redacted_endpoint()}")
else:
    print(
        "\nFAILED to flush spans within the timeout — they were NOT all delivered.\n"
        f"  endpoint: {_redacted_endpoint()}\n"
        "  check the OTLP endpoint/token and your network, then re-run."
    )
    raise SystemExit(1)
