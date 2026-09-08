# Faultline local trace audit — September 8, 2026

## Scope and baseline

Authorized: verify and repair the existing sample-order demonstration, its trace
evidence, and its local walkthrough. No new product features, remote accounts,
Dynatrace renewal, deployment, push, or resume changes. Branch:
`codex/faultline-trace-audit-20260908`; baseline: `c594d5e`.

Preexisting changes are not part of this task: modified `.gitignore`; untracked
`.DS_Store`, `.claude/`, `AGENTS.md`, and `CLAUDE.md`.

Baseline verification:

- Existing suite: 18 passed. One upstream Starlette/httpx deprecation warning.
- Real loopback HTTP: healthy 200; slow 200 with about 2.005 seconds in
  `db.query`; injected failure 500; missing order 404; reset recovery 200.
- The simulated shipping step ran only after a successful, found-order lookup.
- Missing orders in slow mode still returned 404 after the delay. Error mode
  failed before lookup, including for an unknown order ID, and returned 500.
- A temporary loopback collector decoded 22 exported spans over HTTP/protobuf at
  `/v1/traces`, with `service.name=orders-demo`. No external exporter was used.
- Both saved Dynatrace images were visually inspected. They show historical
  successful, roughly two-second, and failed requests; the failure trace shows
  the automatic HTTP server span above the manual `orders.get` and `db.query`.

## Approved changes

1. Preserve the original database exception once per manual span by moving HTTP
   exception conversion outside the `orders.get` context.
2. Add HTTP/trace regressions for the original error, server status, span
   parentage, and omitted shipping on missing/error paths.
3. Correct the portfolio's JSON curl command and trace labels; make the saved
   screenshots readable through full-size links on small screens, without a
   redesign. Keep simulation and expired-trial limits explicit.
4. Execute the actual displayed curl snippet against a temporary local server
   in a regression test, checking failure and recovery.
5. Replace the test that reimplemented the exporter branch with actual isolated
   configuration and loopback protobuf-export tests. Do not change exporter
   behavior unless a demonstrated defect requires it.
6. Update the README's trace anatomy and verified run/test guidance.

## Root causes

- The portfolio's `curl -d` commands omit JSON Content-Type. Curl sends form
  content, FastAPI rejects it with 422, and the fault remains unchanged.
- The page calls `orders.get` automatic/server instrumentation. It is a manual
  INTERNAL span nested beneath `GET /orders/{order_id}`, the automatic SERVER
  span. The ASGI response spans are additional instrumentation.
- The error handler records the database exception, then raises a different
  HTTP exception inside the same span. Automatic span handling records that
  second exception and overwrites the useful error description.
- Default figure margins shrink 1920-pixel evidence images to 264 pixels at a
  390-pixel viewport, with no ordinary link to inspect the original.

## Verification record

Implemented all six approved changes. The only production Python behavior change
is the placement of HTTP error conversion in `app/main.py`; the exporter itself
is unchanged. `conftest.py` now removes inherited `OTEL_*` variables before test
collection imports the app, preventing accidental remote test export.

Regression-first results:

- The original-error test failed against the baseline with two exception events
  on `orders.get` instead of one. It passed after moving HTTP conversion outside
  the span. Both manual spans retain `RuntimeError: database connection failed`;
  the automatic SERVER span remains ERROR with HTTP 500.
- The displayed-command test failed against the baseline with HTTP statuses
  `[422, 200, 422]`. After correcting the HTML snippet, the same extractor and
  real curl execution returned `[200, 500, 200, 200]`, including recovery.
- The real exporter tests passed before the old reimplemented-branch test was
  removed. They exercise actual process-global configuration, repeated setup,
  four request paths, exported trace parentage/status, and the unconfigured case.
  Each isolated app captures 23 local spans (22 request spans plus one setup
  marker); the configured case also proves actual collector receipt.
- Full suite: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest` — 24 passed.
  Three upstream deprecation warnings remain (Starlette/httpx and Uvicorn's
  WebSocket imports). No dependency changes were made for those warnings.

Portfolio browser checks at widths 1440, 390, and 320 pixels:

- Document width equals viewport width; no page-level horizontal overflow.
- Both images load. At 390 pixels, image width is now 344 rather than 264 pixels.
- Both full-size links open the original 1920×992 local PNGs, then Back returns
  to the portfolio. Keyboard navigation reaches both links and the overflowing
  code panels on mobile.
- No page JavaScript errors. Full-page desktop and mobile evidence views were
  visually inspected. External requests, including Google Fonts, were blocked;
  these checks cover the local page and its fallback fonts, not font delivery.

After screenshots: `/private/tmp/faultline-after-desktop.png`,
`/private/tmp/faultline-after-mobile.png`,
`/private/tmp/faultline-after-small.png`. Viewport evidence details:
`/private/tmp/faultline-after-desktop-evidence.png`,
`/private/tmp/faultline-after-mobile-evidence.png`,
`/private/tmp/faultline-after-small-evidence.png`.

Limits: this is a single-process, unauthenticated, local fault demo using three
sample orders. It has no real database, shipping integration, production load,
or currently verified Dynatrace account. The original historical screenshot
includes the old duplicate-exception count; it was preserved, not rewritten to
look like fresh evidence. Local verification does not prove a hosted backend
accepts data now, and no hosted service was contacted.

Before screenshots: `/private/tmp/faultline-before-desktop.png`,
`/private/tmp/faultline-before-mobile.png`,
`/private/tmp/faultline-before-small.png` (1440, 390, and 320 pixels wide).
These local renders blocked external fonts/network requests.

GitNexus: current disk index refreshed to the baseline commit, embeddings 0.
The MCP overview retained its older cached documentation revision; symbol source
matched the inspected code. `get_order` and the replaced exporter-test symbol
both had LOW upstream impact with no graph-discovered callers. Framework route
registration is verified by real HTTP tests rather than assumed from that graph.
Pre-commit `detect_changes` reviewed the eight staged task files and reported
MEDIUM aggregate risk, with one affected process: `get_order → query_order →
get_fault`. That process and its HTTP/error/slow/missing-order paths are covered
by the final 24-pass suite. Staged whitespace validation also passed.
