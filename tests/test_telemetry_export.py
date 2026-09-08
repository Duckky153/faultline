"""Exercise the real process-global setup against a loopback OTLP receiver."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
import pytest


_TRAFFIC = """
import json
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from app import store
from app.main import app
from app.telemetry import configure, get_tracer

provider = trace.get_tracer_provider()
local_spans = InMemorySpanExporter()
provider.add_span_processor(SimpleSpanProcessor(local_spans))
assert configure() is provider
assert configure() is provider
with get_tracer().start_as_current_span("configuration-once"):
    pass

client = TestClient(app)
statuses = []
for mode, order_id in [("none", 1), ("slow", 2), ("error", 3), ("none", 999)]:
    store.set_fault(mode)
    statuses.append(client.get(f"/orders/{order_id}").status_code)
flushed = provider.force_flush()
captured = len(local_spans.get_finished_spans())
provider.shutdown()
print(json.dumps({"statuses": statuses, "flushed": flushed, "local_spans": captured}))
"""


@pytest.fixture
def collector():
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = ExportTraceServiceRequest.FromString(body)
            received.append((self.path, self.headers.get("Content-Type"), message))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive(), "local collector did not stop"


def _run_isolated_app(endpoint=None):
    # Never inherit a user's backend, credentials, or sampling configuration.
    env = {key: value for key, value in os.environ.items() if not key.startswith("OTEL_")}
    env.update(DEMO_SLOW_SECONDS="0.01", PYTHONDONTWRITEBYTECODE="1")
    if endpoint is not None:
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
    result = subprocess.run(
        [sys.executable, "-c", _TRAFFIC], env=env,
        cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "statuses": [200, 200, 500, 404], "flushed": True, "local_spans": 23,
    }


def test_real_configuration_exports_trace_trees_to_local_otlp_collector(collector):
    endpoint, received = collector
    _run_isolated_app(endpoint)
    assert received, "actual configure() did not export to the configured collector"
    spans = []
    for path, content_type, message in received:
        assert path == "/v1/traces"
        assert content_type == "application/x-protobuf"
        for resource in message.resource_spans:
            attrs = {attr.key: attr.value.string_value for attr in resource.resource.attributes}
            assert attrs["service.name"] == "orders-demo"
            for scope in resource.scope_spans:
                spans.extend(scope.spans)

    # One marker proves repeated configure() calls did not duplicate exports.
    assert len([span for span in spans if span.name == "configuration-once"]) == 1
    servers = [span for span in spans if span.kind == 2]  # OTLP SPAN_KIND_SERVER
    assert len(servers) == 4
    assert sorted(span.status.code for span in servers) == [0, 0, 0, 2]
    orders = [span for span in spans if span.name == "orders.get"]
    assert len(orders) == 4
    assert sorted(span.status.code for span in orders) == [0, 0, 1, 2]
    for order in orders:
        parent = next(span for span in servers if span.span_id == order.parent_span_id)
        assert order.trace_id == parent.trace_id
    assert len([span for span in spans if span.name == "downstream.shipping"]) == 2


def test_unconfigured_app_handles_requests_without_an_export_destination(collector):
    _, received = collector
    _run_isolated_app()
    assert received == []
