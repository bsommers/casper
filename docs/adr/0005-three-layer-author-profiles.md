# ADR 0005 — Three-Layer Author Profiles with Mode 0600 Local Layer and Tamper Guard

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/unit/test_layers.py`, `tests/security/test_privacy.py`

## Context

Generated profiles must be regeneratable without losing curated tweaks or leaking private contact data.

## Decision

Split each author into generated `<id>.yaml`, tracked `<id>.curated.yaml`, and gitignored `<id>.local.yaml` created atomically with `0600` permissions. Protect `<id>.yaml` via `body_sha256` tamper checks.

## Consequences

Strict privacy boundary and reversible non-destructive curation.
