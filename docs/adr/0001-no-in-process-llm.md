# ADR 0001 — No In-Process LLM or Hugging Face; Deterministic Rule-Based Realization Default

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/security/test_constraints.py`

## Context

Casper must run offline, reproducibly, and without heavyweight ML/LLM SDK dependencies (amended by ADR 0010 for opt-in external CLI subprocesses).

## Decision

Forbid Hugging Face and Python LLM client SDKs in dependencies and source imports. Default realization uses deterministic rule-based rewriting.

## Consequences

Byte-identical outputs by default, minimal dependency footprint, and fast offline CI.
