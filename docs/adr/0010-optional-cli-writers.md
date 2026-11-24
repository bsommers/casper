# ADR 0010 — Optional Claude and Antigravity CLI Writers Behind Explicit Opt-In and Fallback

**Status:** accepted  
**Date:** 2026-11-20  
**Enforced by:** `tests/integration/test_llm.py`

## Context

Rule-based rewrites have bounded stylistic range; users with local `claude` or `agy` CLIs benefit from opt-in fluent drafting.

## Decision

Support `--backend claude|agy` via isolated subprocess invocation (`shell=False`, empty temp `cwd`, minimal env, strict privacy allowlist) with automatic fallback to `rules` unless `--no-fallback` is set.

## Consequences

Zero external execution by default, safe opt-in assistance, and deterministic fallback.
