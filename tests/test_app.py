from __future__ import annotations

import os

# Keep the "slow" fault fast during tests.
os.environ.setdefault("DEMO_SLOW_SECONDS", "0.05")

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app import store
from app.main import app

# Capture spans in memory so tests can assert what was emitted.
_exporter = InMemorySpanExporter()
trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(_exporter))

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    store.set_fault("none")
    _exporter.clear()
    yield
    store.set_fault("none")


def _spans_by_name() -> dict:
    return {s.name: s for s in _exporter.get_finished_spans()}


def _span_names() -> set[str]:
    return {s.name for s in _exporter.get_finished_spans()}


# ---------------------------------------------------------------- basics

def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_read_fault_default_is_none():
    assert client.get("/admin/fault").json() == {"mode": "none"}


def test_list_orders_returns_all():
    r = client.get("/orders")
    assert r.status_code == 200
    assert len(r.json()["orders"]) == 3


def test_missing_order_is_404():
    assert client.get("/orders/999").status_code == 404


def test_unknown_fault_mode_rejected():
    r = client.post("/admin/fault", json={"mode": "explode"})
    assert r.status_code == 400


@pytest.mark.parametrize("mode", ["none", "slow", "error"])
def test_fault_mode_roundtrips(mode):
    assert client.post("/admin/fault", json={"mode": mode}).json() == {"mode": mode}
    assert client.get("/admin/fault").json() == {"mode": mode}


# ---------------------------------------------------------------- the trace

def test_get_order_emits_the_full_trace():
    r = client.get("/orders/1")
    assert r.status_code == 200
    assert r.json()["item"] == "Blue Widget"
    assert r.json()["tracking"] == "TRK0001"
    assert {"orders.get", "db.query", "downstream.shipping"} <= _span_names()


def test_list_orders_emits_list_spans():
    client.get("/orders")
    assert {"orders.list", "db.list"} <= _span_names()


def test_trace_is_one_tree():
    """db.query and downstream.shipping are children of the request span,
    and the whole thing shares one trace id — i.e. it's a real trace, not
    three unrelated spans."""
    client.get("/orders/1")
    spans = _spans_by_name()
    request, db, ship = spans["orders.get"], spans["db.query"], spans["downstream.shipping"]

    assert db.context.trace_id == request.context.trace_id == ship.context.trace_id
    assert db.parent is not None and db.parent.span_id == request.context.span_id
    assert ship.parent is not None and ship.parent.span_id == request.context.span_id


def test_db_query_records_attributes():
    client.get("/orders/1")
    db = _spans_by_name()["db.query"]
    assert db.attributes.get("db.order_id") == 1
    assert db.attributes.get("fault.mode") == "none"
    assert db.attributes.get("db.found") is True


# ---------------------------------------------------------------- the break button

def test_fault_error_returns_500_and_marks_spans():
    client.post("/admin/fault", json={"mode": "error"})
    r = client.get("/orders/1")
    assert r.status_code == 500

    spans = _spans_by_name()
    # the failing step and the request span are both flagged as errors
    assert spans["db.query"].status.status_code.name == "ERROR"
    assert spans["orders.get"].status.status_code.name == "ERROR"
    # the exception is recorded on the trace, so a backend can show the cause
    assert any(e.name == "exception" for e in spans["orders.get"].events)


def test_error_never_reaches_downstream():
    """When the database step fails, the shipping step is never run — so the
    trace shows precisely where the request died."""
    client.post("/admin/fault", json={"mode": "error"})
    client.get("/orders/1")
    names = _span_names()
    assert "db.query" in names
    assert "downstream.shipping" not in names


def test_fault_slow_tags_the_span_and_adds_latency():
    client.post("/admin/fault", json={"mode": "slow"})
    r = client.get("/orders/2")
    assert r.status_code == 200

    db = _spans_by_name()["db.query"]
    assert db.attributes.get("fault.mode") == "slow"
    elapsed_seconds = (db.end_time - db.start_time) / 1e9
    assert elapsed_seconds >= 0.04  # DEMO_SLOW_SECONDS == 0.05 under test


# -------------------------------------------- not-found / slow are NOT failures

def test_missing_order_does_not_mark_span_error():
    """A 404 is a normal client outcome — it must NOT flag orders.get as ERROR,
    or 'order not found' would inflate the Dynatrace failure rate."""
    r = client.get("/orders/999")
    assert r.status_code == 404

    orders_get = _spans_by_name()["orders.get"]
    assert orders_get.status.status_code.name != "ERROR"
    # no exception event was recorded for a plain not-found
    assert not any(e.name == "exception" for e in orders_get.events)


def test_slow_mode_is_200_and_not_marked_error():
    """'slow' is added latency, not a failure — the request still succeeds and
    neither span is flagged ERROR."""
    client.post("/admin/fault", json={"mode": "slow"})
    r = client.get("/orders/2")
    assert r.status_code == 200

    spans = _spans_by_name()
    assert spans["orders.get"].status.status_code.name != "ERROR"
    assert spans["db.query"].status.status_code.name != "ERROR"


def test_database_failure_records_original_error_once_per_manual_span():
    store.set_fault("error")
    response = client.get("/orders/1")
    assert response.status_code == 500
    assert response.json() == {"detail": "order lookup failed"}

    spans = _spans_by_name()
    for name in ("db.query", "orders.get"):
        span = spans[name]
        exceptions = [event for event in span.events if event.name == "exception"]
        assert len(exceptions) == 1
        assert exceptions[0].attributes["exception.type"] == "RuntimeError"
        assert exceptions[0].attributes["exception.message"] == "database connection failed"
        assert span.status.status_code.name == "ERROR"
        assert "database connection failed" in span.status.description

    server = spans["GET /orders/{order_id}"]
    assert server.kind.name == "SERVER"
    assert server.status.status_code.name == "ERROR"
    assert server.attributes["http.status_code"] == 500
    assert "downstream.shipping" not in spans


def test_manual_order_span_is_nested_beneath_automatic_http_server_span():
    client.get("/orders/1")
    spans = _spans_by_name()
    server = spans["GET /orders/{order_id}"]
    manual = spans["orders.get"]
    assert server.kind.name == "SERVER"
    assert manual.kind.name == "INTERNAL"
    assert manual.parent.span_id == server.context.span_id
    assert manual.context.trace_id == server.context.trace_id


@pytest.mark.parametrize("mode", ["none", "slow"])
def test_missing_order_never_reaches_shipping_or_marks_server_error(mode):
    store.set_fault(mode)
    response = client.get("/orders/999")
    assert response.status_code == 404
    spans = _spans_by_name()
    assert spans["db.query"].attributes["db.found"] is False
    assert spans["GET /orders/{order_id}"].status.status_code.name != "ERROR"
    assert "downstream.shipping" not in spans
