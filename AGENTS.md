# AGENTS.md — Casper Developer & Agent Guide

## Verification Gate (Single Source of Truth)

Run the tiered verification gate before any commit or release:

```bash
# Fast pre-commit gate (ruff, mypy, spec-sync, secret-scan, smoke, unit)
scripts/verify.sh --quick

# Pre-milestone gate (functional + security tiers)
scripts/verify.sh --tier smoke,unit,integration,system,security

# Full pre-release gate (all 8 tiers + coverage >=90% line / >=85% branch)
scripts/verify.sh
```

`scripts/verify.sh` emits exactly one line to stdout (`PASS ...` or `FAIL ...`) and writes detailed logs to `target/verify/`.

## Architecture & Module Rank DAG

Imports inside `src/casper/` must flow strictly downward (`rank(A) > rank(B)`):

- **Rank 1:** `errors`, `models`, `documents`, `parsing`, `libraries`, `rewrites`
- **Rank 2:** `loaders.*`, `features.*`, `profile`
- **Rank 3:** `layers`, `conformance`, `facts`
- **Rank 4:** `catalog`, `planner`, `modalities`
- **Rank 5:** `realizer`, `llm`, `validator` (`validator` must never import `realizer` or `llm`)
- **Rank 6:** `pipeline`
- **Rank 7:** `commands` (10 typed operations; must never import `cli` or `web`)
- **Rank 8:** `web.server`, `cli`, `__init__`

## Global Constraints

- **No Hugging Face or Python LLM SDKs** (GC-01): subprocess calls to `claude`/`agy` CLI only behind explicit opt-in.
- **Deterministic by default** (GC-03): same inputs + profile + libraries + seed produce byte-identical outputs.
- **Zero-invention fact traceability** (GC-04): every non-frame sentence cites valid `Fact.id`s.
- **Strict privacy boundary** (GC-05): private email/consent live only in gitignored `authors/<id>.local.yaml` (mode `0600`) and never enter external CLI prompts.
- **Localhost-only web server** (GC-06): binds exclusively to `127.0.0.1`.
- **Zero external network in default tests** (GC-07): enforced by `tests/conftest.py`.
- **Spec & brand sync:** run `scripts/build_spec.py` after editing `spec/0[0-9]-*.md` and `scripts/build_brand.py` after editing brand generation.
