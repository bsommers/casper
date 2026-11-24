# ADR 0012 — Shared rewrites.py Registry, Tightened Ask Cues, Dual FidelityMode & Ghost Brand Kit

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/unit/test_facts.py`, `tests/unit/test_realizer.py`, `tests/unit/test_validator.py`, `tests/smoke/test_brand.py`

## Context

Draft review identified hidden writer/validator coupling, false-positive `review` ask triggers, assisted polarity flips, and visual identity needs.

## Decision

Place `REWRITE_RULES` in Rank-1 `rewrites.py`; tighten `ask` cues with inline `[kind]` tags and `extract_facts`; enforce dual `STRICT`/`ASSISTED` validation including per-fact polarity checks; generate deterministic Casper ghost brand assets via `scripts/build_brand.py`.

## Consequences

Acyclic architecture, eliminated unsolicited CTAs, hardened assisted validation, and cohesive brand assets.
