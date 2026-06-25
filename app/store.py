"""A tiny in-memory 'database' for the orders demo — plus the break button.

The fault mode is the demo's whole point: flip it to "slow" or "error" and the
database step starts taking too long or failing, which is exactly what you then
watch Dynatrace catch and pin down.
"""
from __future__ import annotations

import os
import threading
import time

from app.telemetry import get_tracer

tracer = get_tracer()

# fault mode: "none" | "slow" | "error"
# Sync FastAPI endpoints run in a threadpool, so concurrent requests can read
# and write this switch at the same time — guard it with a lock.
_fault_lock = threading.Lock()
_fault = {"mode": "none"}

_ORDERS = {
    1: {"id": 1, "item": "Blue Widget", "status": "shipped"},
    2: {"id": 2, "item": "Red Gadget", "status": "processing"},
    3: {"id": 3, "item": "Green Gizmo", "status": "delivered"},
}

VALID_FAULTS = ("none", "slow", "error")


def set_fault(mode: str) -> None:
    if mode not in VALID_FAULTS:
        raise ValueError(f"unknown fault mode: {mode!r} (use one of {VALID_FAULTS})")
    with _fault_lock:
        _fault["mode"] = mode


def get_fault() -> str:
    with _fault_lock:
        return _fault["mode"]


def query_order(order_id: int) -> dict:
    """Simulate a DB lookup as its own span, honoring the current fault mode."""
    mode = get_fault()  # one consistent, lock-guarded snapshot for this lookup
    with tracer.start_as_current_span("db.query") as span:
        span.set_attribute("db.order_id", order_id)
        span.set_attribute("fault.mode", mode)

        if mode == "slow":
            slow_seconds = float(os.getenv("DEMO_SLOW_SECONDS", "2.0"))
            time.sleep(slow_seconds)
        if mode == "error":
            raise RuntimeError("database connection failed")

        order = _ORDERS.get(order_id)
        span.set_attribute("db.found", order is not None)
        return dict(order) if order else {}


def list_orders() -> list[dict]:
    with tracer.start_as_current_span("db.list"):
        return [dict(o) for o in _ORDERS.values()]
