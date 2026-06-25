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
    with tracer.start_as_current_span("orders.get") as span:
        span.set_attribute("order.id", order_id)
        try:
            order = store.query_order(order_id)
        except RuntimeError as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, "order lookup failed"))
            raise HTTPException(status_code=500, detail="order lookup failed") from exc

        if not order:
            # "Not found" is a normal client outcome, not a server failure, so
            # mark the span OK explicitly and raise the 404 *after* the span has
            # closed — otherwise the exception would unwind through the span and
            # get recorded as an error, inflating the Dynatrace failure rate.
            # (A real fault raises 500 above and is correctly marked ERROR.)
            span.set_status(Status(StatusCode.OK))
            order = None
        else:
            # A downstream call (e.g. a shipping service) shown as its own step.
            with tracer.start_as_current_span("downstream.shipping"):
                order["tracking"] = f"TRK{order_id:04d}"

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
