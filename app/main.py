"""orders-demo: a tiny web service you instrument, ship to Dynatrace, and break.

Endpoints:
  GET  /health            -> liveness check
  GET  /orders            -> list all orders
  GET  /orders/{id}       -> one order (db lookup span + a downstream span)
  GET  /admin/fault       -> read the current break-button mode
  POST /admin/fault       -> set it: {"mode": "none" | "slow" | "error"}
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel

from app import store
from app.telemetry import get_tracer

tracer = get_tracer()
app = FastAPI(title="orders-demo")
# Auto-instrument HTTP requests: each call becomes a SERVER span under the
# "orders-demo" service, so the app shows up as a real service in Dynatrace
# (with request counts, latency, and failures). Our manual spans nest beneath it.
FastAPIInstrumentor.instrument_app(app)


class FaultRequest(BaseModel):
    mode: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/orders")
def list_orders() -> dict:
    with tracer.start_as_current_span("orders.list"):
        return {"orders": store.list_orders()}


@app.get("/orders/{order_id}")
def get_order(order_id: int) -> dict:
    try:
        with tracer.start_as_current_span("orders.get") as span:
            span.set_attribute("order.id", order_id)
            order = store.query_order(order_id)

            if not order:
                # Close the span before raising an ordinary client-side 404.
                span.set_status(Status(StatusCode.OK))
                order = None
            else:
                # Local simulation only: no shipping service is contacted.
                with tracer.start_as_current_span("downstream.shipping"):
                    order["tracking"] = f"TRK{order_id:04d}"
    except RuntimeError as exc:
        # The span has already recorded the original database exception once.
        # Translate it outside the span so HTTPException neither adds a second
        # event nor replaces the original error description. HTTP instrumentation
        # still marks the enclosing SERVER span as failed when it sees the 500.
        raise HTTPException(status_code=500, detail="order lookup failed") from exc

    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.get("/admin/fault")
def read_fault() -> dict:
    return {"mode": store.get_fault()}


@app.post("/admin/fault")
def set_fault(req: FaultRequest) -> dict:
    try:
        store.set_fault(req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"mode": store.get_fault()}
