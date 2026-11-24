# ADR 0004 — input/ and output/ Git-Ignored with README.md Placeholders

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `.gitignore` and `tests/smoke/test_hygiene.py`

## Context

Users place private notes and generated drafts in local `input/` and `output/` directories that must never be committed accidentally.

## Decision

Ignore `input/*` and `output/*` while tracking `input/README.md` and `output/README.md`.

## Consequences

Clean-clone workspaces have documented local sandboxes with zero leakage risk.
