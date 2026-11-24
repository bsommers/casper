# ADR 0011 — Localhost-Only Python Stdlib ThreadingHTTPServer and Frameworkless Static UI

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/security/test_web_security.py`, `tests/system/test_web_e2e.py`

## Context

Users need an approachable interactive UI without adding Node/JS build pipelines or exposing local notes on the LAN.

## Decision

Serve a frameworkless static UI from Python's stdlib `ThreadingHTTPServer` bound strictly to `127.0.0.1` with strict Host/Origin/Sec-Fetch-Site/CSP guards and `textContent`-only DOM rendering.

## Consequences

Zero frontend build complexity and defense-in-depth against CSRF/XSS/DNS rebinding.
