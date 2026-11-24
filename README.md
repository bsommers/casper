![Casper — The Friendly Ghostwriter](docs/brand/casper-logo-light.svg)

# Casper — The Friendly Ghostwriter

Casper is a local-first, deterministic ghostwriting toolkit exposed uniformly through a Python library (`casper.*`), a CLI (`casper`), and a localhost-only Web UI (`casper serve`). It extracts structured, cited facts from source materials, plans drafts across audience personas and output modalities, scores voice conformance against author profiles, and verifies zero-invention fact traceability.

- **Showcase & Documentation Site:** [bsommers.github.io/casper](https://bsommers.github.io/casper/) · Local entrypoint: [docs/index.html](docs/index.html)
- **Brand Kit, Stickers & Wallpapers:** Self-contained SVGs and PNGs for dark/light desktop monitors (`1920x1080`–`3480x1440`) and phones (`1170x2532`–`1440x3120`) in [docs/brand/wallpapers/](docs/brand/wallpapers/) (see [docs/index.html](docs/index.html) for the interactive gallery).

## Quickstart

### Install

Using `uv` (recommended) or `pip`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### Generate a Draft (`casper write`)

```bash
.venv/bin/casper write \
  --structure status_update \
  --modality slack \
  --source developer \
  --target management \
  --input examples/edge-migration-status.md
```

### Start & Stop the Localhost Web UI

```bash
scripts/start.sh --background --open
scripts/stop.sh
```

`scripts/start.sh` bootstraps `.venv` if needed, binds strictly to `127.0.0.1` (default port `8731`), and writes its PID/log under `target/`.

## Architecture Summary

Casper enforces a strict downward-only module rank DAG inside `src/casper/` (checked by AST in `tests/smoke/test_architecture.py`):

- **Rank 1:** `errors`, `models`, `documents`, `parsing`, `libraries`, `rewrites`
- **Rank 2:** `loaders.*`, `features.*`, `profile`
- **Rank 3:** `layers`, `conformance`, `facts`
- **Rank 4:** `catalog`, `planner`, `modalities`
- **Rank 5:** `realizer`, `llm`, `validator` (`validator` never imports `realizer` or `llm`)
- **Rank 6:** `pipeline`
- **Rank 7:** `commands` — uniform 10-command core (`write_draft`, `extract_facts`, `score_draft`, `list_options`, `backend_status`, `author_build`, `author_inspect`, `author_show`, `author_list`, `author_diff`); never imports `cli` or `web`
- **Rank 8:** `web.server`, `cli`, `__init__`

By default, realization runs offline and deterministically via the built-in rule-based engine (`backend="rules"`). Optional external CLI writers (`claude` and `agy`) run only behind explicit opt-in (`--backend claude|agy`) with zero in-process LLM or Hugging Face SDKs, strict zero-invention validation, and configurable fallback to `rules`.

## Verification

```bash
# Fast pre-commit gate (ruff, mypy, spec-sync, secret-scan, smoke, unit)
scripts/verify.sh --quick

# Pre-milestone gate (functional + security tiers)
scripts/verify.sh --tier smoke,unit,integration,system,security

# Full pre-release gate (all 8 test tiers + coverage >=90% line / >=85% branch)
scripts/verify.sh
```

## Documentation

- [Using Casper](docs/using.md) — CLI workflows, operational scripts, three-layer author profiles, and worked examples
- [Data Model & Libraries](docs/data-model.md) — Core dataclasses/enums, 32-feature voice schema, and shipped YAML libraries
- [API Reference](docs/api-reference.md) — Python public API, surface parity matrix, and localhost HTTP endpoints
- [Testing & Verification](docs/testing.md) — 8-tier test suite, coverage gates, offline guards, and sync checks
- [Architecture Decision Records](docs/adr/README.md) — Accepted and proposed design decisions
- [Technical Specification](SPEC.md) — Complete compiled specification
- [Worked Example Input](examples/edge-migration-status.md) — Sample status notes used to generate `examples/outputs/`
