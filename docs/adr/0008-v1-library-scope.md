# ADR 0008 — v1 Library Scope: 10 Personas, 3 Structures, 5 Modalities, 1 Default Glossary

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/unit/test_libraries.py`

## Context

Tunable writing behavior must live in declarative YAML rather than hardcoded branches.

## Decision

Ship 5 source + 5 target personas, 3 structures (11 valid structure x modality pairs), 5 modalities, 1 default glossary, phrasebank, and lexicons under `src/casper/data/` with `project_dir` overrides.

## Consequences

Predictable, customizable library surface with deterministic config digest.
