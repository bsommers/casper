# ADR 0006 — Profile-Relative Deterministic 32-Feature Voice Conformance Score

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/unit/test_conformance.py`

## Context

Leave-one-out measurements show 74-87/100 on held-out author prose vs. 18-61/100 on out-of-register text.

## Decision

Score candidate prose deterministically against 32 `STABILITY_KEYS` features, 60 function words, and optional `structure` dimension using geometric mean with provisional bands 80/65/45 and confidence tiers <250/250-999/>=1000.

## Consequences

Fast, offline, explainable voice scoring with explicit gap diagnostics.
