# ADR 0009 — Every Non-Frame Sentence Cites Facts; Candidate Variants Ranked by Voice Score

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/unit/test_realizer.py`, `tests/unit/test_validator.py`

## Context

Ghostwritten output must never invent claims while still matching an author's voice.

## Decision

Bind every non-frame sentence to one or more explicit `Fact.id` citations and rank rule-generated candidate variants by voice conformance score.

## Consequences

Full sentence-level provenance and verifiable zero-invention guarantees.
