# Faultline

A tiny web service instrumented with OpenTelemetry and built to be broken on
purpose, so the resulting failure surfaces on its own in a tracing backend. Flip
one switch, a step inside the app starts failing, and the trace points straight
at the step that broke.

> **Naming:** the project is **Faultline**; the running service reports itself as
> `orders-demo`, so that's the name it appears under in the tracing backend.

## What it is
A pretend online-store "orders" service with three in-memory sample orders. An
order lookup records a **trace**: a timed record of the request, the lookup, and
a simulated shipping step that adds a sample tracking number. There is no real
database or shipping-service call. A **fault switch** makes the lookup slow or
fail, so that behavior can be reproduced and inspected end to end.

FastAPI instrumentation adds the automatic `GET /orders/{order_id}` SERVER span.
The manually created `orders.get` INTERNAL span sits beneath it, with `db.query`
and, only after a successful found-order lookup, `downstream.shipping` as children.
The automatic HTTP response spans are additional steps, not database or shipping
calls. A database failure records the original exception once on each affected
manual span and returns HTTP 500. A missing order returns 404 without marking the
server span as failed; it never reaches the simulated shipping step.

## The four parts
1. **The app** — `app/main.py`. A few endpoints: list orders, get one order, a
   health check, and the fault switch.
2. **The instrumentation** — `app/telemetry.py`. The OpenTelemetry setup: it turns
   each request into a trace and, when an OTLP destination is configured, ships
   those traces there. No destination = it just runs locally.
3. **The store + fault switch** — `app/store.py`. Holds three in-memory orders and
   the fault mode (`none` / `slow` / `error`).
4. **The tests** — `tests/`. 24 checks cover responses, trace parentage, errors,
   missing orders, the actual portfolio curl commands, and real OTLP/HTTP export
   to a temporary loopback collector.

## Run it locally
```bash
uv venv --python 3.12
VIRTUAL_ENV="$PWD/.venv" uv pip install -e ".[dev]"
.venv/bin/python -m pytest                       # run the 24 tests
.venv/bin/python -m uvicorn app.main:app --port 8799   # start the server
```
Then, in another terminal:
```bash
curl localhost:8799/orders/1                     # a normal, healthy order
curl -X POST localhost:8799/admin/fault -H 'content-type: application/json' -d '{"mode":"error"}'
curl localhost:8799/orders/1                      # now it's broken (HTTP 500)
curl -X POST localhost:8799/admin/fault -H 'content-type: application/json' -d '{"mode":"none"}'  # fix it
```
Fault modes: `slow` (the database step drags), `error` (it fails), `none` (healthy).
The default slow delay is two seconds; tests use a shorter delay. The switch is
process-local and unauthenticated, intended only for this local demonstration.
Do not expose it publicly or treat it as a production administration endpoint.

The tests require `curl` and permission to bind temporary ports on `127.0.0.1`.
They clear inherited `OTEL_*` settings before app import, and export tests set
their own loopback destination. Tests do not load `.env`, use Dynatrace, or need
an account. The portfolio's displayed commands are extracted from the HTML and
executed against the local service, including a recovery request.

## Send the traces to a backend
The configured exporter uses OTLP over HTTP/protobuf. Point it at a compatible
HTTP ingestion endpoint, not a gRPC port. The existing setup reads
`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`:

1. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at the destination (and, for a hosted
   backend, supply an auth token). For a local Jaeger, run the all-in-one image and
   point at its OTLP port. For Dynatrace, create an access token with the
   `openTelemetryTrace.ingest` permission and use the tenant's OTLP address.
2. Copy `.env.example` to `.env`, fill in the endpoint (and token), then `source .env`.
3. Start the server again. The exporter sends completed spans to that endpoint;
   confirm their receipt in the backend before claiming delivery.
4. Flip the fault switch to `error`, and the failing database step is flagged in the
   backend on its own.

Any token lives only in `.env`, which is gitignored and never committed.

## Screenshots
The images under `screenshots/` and `dashboard/` were captured during a past
Dynatrace trial session (that trial has since expired). In them the `orders-demo`
service appears on its own, and a failing request's trace marks the `db.query` step
as an error reported by the app's instrumentation. They prove historical receipt,
not a currently active Dynatrace connection. The local portfolio at
`dashboard/index.html` links to the full-size images for inspection.

See [the September 8 local audit](2026-09-08-trace-audit.md) for reproduced defects,
regression results, screenshot paths, and the boundaries of this verification.
