# Faultline

A tiny web service instrumented with OpenTelemetry and built to be broken on
purpose, so the resulting failure surfaces on its own in a tracing backend. Flip
one switch, a step inside the app starts failing, and the trace points straight
at the step that broke.

> **Naming:** the project is **Faultline**; the running service reports itself as
> `orders-demo`, so that's the name it appears under in the tracing backend.

## What it is
A pretend online-store "orders" service. Every time an order is looked up, the app
records a step-by-step **trace** of what it did (look up the order in the database
→ call a shipping service). A **fault switch** makes the database step slow or
fail, so an outage can be reproduced on demand and watched end to end.

## The four parts
1. **The app** — `app/main.py`. A few endpoints: list orders, get one order, a
   health check, and the fault switch.
2. **The instrumentation** — `app/telemetry.py`. The OpenTelemetry setup: it turns
   each request into a trace and, when an OTLP destination is configured, ships
   those traces there. No destination = it just runs locally.
3. **The store + fault switch** — `app/store.py`. Holds three in-memory orders and
   the fault mode (`none` / `slow` / `error`).
4. **The tests** — `tests/test_app.py`. 18 automated checks that the app responds,
   the trace has the right spans, and the fault switch actually breaks the request.

## Run it locally
```bash
uv venv --python 3.12
VIRTUAL_ENV="$PWD/.venv" uv pip install fastapi "uvicorn[standard]" \
  opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-http \
  opentelemetry-instrumentation-fastapi pytest httpx
.venv/bin/python -m pytest                       # run the 18 tests
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

## Send the traces to a backend
Because the app exports over OTLP, its traces flow into any OTLP-compatible backend
with no code change — a local Jaeger, or a hosted tool like Dynatrace:

1. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at the destination (and, for a hosted
   backend, supply an auth token). For a local Jaeger, run the all-in-one image and
   point at its OTLP port. For Dynatrace, create an access token with the
   `openTelemetryTrace.ingest` permission and use the tenant's OTLP address.
2. Copy `.env.example` to `.env`, fill in the endpoint (and token), then `source .env`.
3. Start the server again — every request now shows up as a trace in the configured
   backend.
4. Flip the fault switch to `error`, and the failing database step is flagged in the
   backend on its own.

Any token lives only in `.env`, which is gitignored and never committed.

## Screenshots
The images under `screenshots/` and `dashboard/` were captured during a past
Dynatrace trial session (that trial has since expired). In them the `orders-demo`
service appears on its own, and a failing request's trace marks the `db.query` step
as the cause — found automatically, not guessed.
