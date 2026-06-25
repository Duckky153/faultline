# Faultline — your Dynatrace interview demo

A tiny web service you can **instrument, send into Dynatrace, break on purpose, and watch Dynatrace catch.** This is the live demo for the Solutions Engineer interview — and a real project for your résumé once it's wired to Dynatrace.

> **Naming:** the project is **Faultline**; the running service reports itself as `orders-demo`, so that's the name it appears under in Dynatrace.

## What it is, in one breath
It's a pretend online-store "orders" service. Every time someone looks up an order, the app writes a little step-by-step diary of what it did (look up the order in the database → call a shipping service). That diary is a **trace** (the standard name for "the story of one request"). A **break button** lets you make the database step slow or fail, so you can show what a real outage looks like.

## The four parts (this is the whole thing)
1. **The app** — `app/main.py`. A few web pages: list orders, get one order, a health check, and the break button.
2. **The shipping labels** — `app/telemetry.py`. This is the OpenTelemetry setup: it turns each request into a trace and, *if you give it a Dynatrace address*, ships those traces there. No address = it just runs locally.
3. **The fake database + the break button** — `app/store.py`. Holds three orders and the fault switch (`none` / `slow` / `error`).
4. **The tests** — `tests/test_app.py`. 18 automated checks that prove it all works (the app responds, the trace has the right steps, the break button actually breaks it).

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
Break modes: `slow` (the database step drags), `error` (it fails), `none` (healthy).

## Send it to Dynatrace (the last step — needs your free trial)
1. Start a free Dynatrace trial (no credit card): https://www.dynatrace.com/try-free/
2. In Dynatrace, create an **access token** with the `openTelemetryTrace.ingest` permission.
3. Copy `.env.example` to `.env`, paste in your Dynatrace OTLP address + token, then `source .env`.
4. Start the server again — now every request shows up in **your** Dynatrace as a trace.
5. Press the break button and watch Dynatrace flag the failing step.

Your token lives only in `.env` (which is gitignored) — it never gets committed.

## The story you tell in the interview
*"I built a small app, instrumented it with OpenTelemetry, and sent its data into Dynatrace. Then I broke one step on purpose — and Dynatrace pinpointed exactly which step failed, without me telling it. For a real store, that failing step is customers who can't check out, so finding it in seconds instead of hours is real money saved."*
