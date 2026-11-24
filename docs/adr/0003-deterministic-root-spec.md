# ADR 0003 — Root SPEC.md Deterministically Generated from spec/0[0-9]-*.md

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/smoke/test_spec.py`

## Context

Maintaining both modular spec chapters and a single monolithic root SPEC.md by hand causes silent drift.

## Decision

Generate root `SPEC.md` deterministically via `scripts/build_spec.py` and verify zero drift in `scripts/verify.sh`.

## Consequences

Single source of truth in `spec/0[0-9]-*.md` with guaranteed sync.
