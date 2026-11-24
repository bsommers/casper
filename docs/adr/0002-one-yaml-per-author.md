# ADR 0002 — Author Profiles Stored as One YAML File per Author in authors/

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/unit/test_profile.py`

## Context

Author voice fingerprints should be human-inspectable, diffable in git, and modular per author.

## Decision

Store each generated author profile as `authors/<id>.yaml` with schema version 1 and canonical `body_sha256`.

## Consequences

Simple file-based catalog management and clean diffs per author.
