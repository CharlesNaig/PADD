# PADD Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dark, responsive PADD dashboard that runs from a Raspberry Pi on localhost and preserves the NAIG Tiny hardware telemetry.

**Architecture:** A dependency-free Python HTTP service serves static browser assets and a normalized `/api/status` payload. The collector combines Pi-hole v6 `/api/padd` data with local Raspberry Pi telemetry, caches short-lived readings, and degrades to explicit unavailable states. The browser selects full, regular, tiny, or clean density automatically, with a persistent manual override.

**Tech Stack:** Python 3 standard library, semantic HTML, modern CSS, vanilla JavaScript, `unittest`.

---

## File structure

- `padd_web/server.py`: CLI, HTTP routes, cache, Pi-hole session client, local hardware collector, normalized payload.
- `padd_web/static/index.html`: semantic dashboard shell and accessible controls.
- `padd_web/static/app.css`: design tokens and responsive/density layouts.
- `padd_web/static/app.js`: polling, formatting, DOM updates, mode persistence, stale/error handling.
- `tests/test_web_server.py`: collector, normalization, caching, routing, and path-safety tests.
- `padd-web.sh`: Raspberry Pi launcher.
- `README.md`: install, authentication, startup, and kiosk instructions.

### Task 1: Collector contract and tests

**Files:**
- Create: `tests/test_web_server.py`
- Create: `padd_web/__init__.py`
- Create: `padd_web/server.py`

- [ ] Define a stable payload with `meta`, `status`, `summary`, `system`, `network`, `hardware`, `activity`, and `versions` objects.
- [ ] Test nested-value lookup, numeric coercion, UPS little-endian parsing, and status priority.
- [ ] Run `python -m unittest tests.test_web_server -v`; expect the focused suite to pass.

### Task 2: Raspberry Pi and Pi-hole data collection

**Files:**
- Modify: `padd_web/server.py`
- Test: `tests/test_web_server.py`

- [ ] Implement Pi-hole v6 authentication using `/api/auth`, including local `/etc/pihole/cli_pw` discovery and SID reuse.
- [ ] Fetch `/api/padd`, normalize privacy-hidden fields, and retain a clear connection error without stopping local telemetry.
- [ ] Read CPU/load/memory/network from Python and `/proc`, `vcgencmd` power/Vcore, and EP-0136 registers `0x13`/`0x14` through `i2cget`.
- [ ] Add a thread-safe two-second cache so multiple browser tabs do not hammer I2C or Pi-hole.

### Task 3: Local HTTP service

**Files:**
- Modify: `padd_web/server.py`
- Test: `tests/test_web_server.py`

- [ ] Serve only allow-listed static files with correct MIME and no directory traversal.
- [ ] Expose `/api/status` and `/api/health` JSON with no-cache headers.
- [ ] Add CLI options for host, port, API URL, password, TOTP, refresh interval, and demo data.
- [ ] Bind to `127.0.0.1` by default and print the usable dashboard URL.

### Task 4: Responsive instrument-panel UI

**Files:**
- Create: `padd_web/static/index.html`
- Create: `padd_web/static/app.css`
- Create: `padd_web/static/app.js`

- [ ] Build a semantic live dashboard with health, blocking, queries, CPU, memory, network, activity, versions, and NAIG power/UPS readings.
- [ ] Implement the phosphor instrument palette (`#06100d`, `#0b1814`, `#63dc8c`, `#6fc8d8`, `#f0bd62`, `#ef6b68`) and offline-safe type stacks.
- [ ] Make full, regular, tiny, and clean densities work via container/media queries and a saved user override.
- [ ] Respect reduced motion, keyboard focus, screen-reader live regions, touch targets, and safe-area insets.

### Task 5: Raspberry Pi handoff and verification

**Files:**
- Create: `padd-web.sh`
- Modify: `README.md`

- [ ] Add one-command startup and document password-free local Pi-hole access through `/etc/pihole/cli_pw`.
- [ ] Document LAN binding as an explicit opt-in and include a Chromium kiosk example.
- [ ] Run all Python tests and a local server smoke test.
- [ ] Capture and inspect screenshots at full, regular, tiny, and clean widths; correct overflow or hierarchy problems.

