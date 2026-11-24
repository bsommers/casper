# Testing & Verification

Casper uses an 8-tier pytest suite orchestrated by [`scripts/verify.sh`](../scripts/verify.sh), paired with static quality checks and deterministic generator checks.

## Verification Gate (`scripts/verify.sh`)

`scripts/verify.sh` emits a single summary line (`PASS ...` or `FAIL ...`) to stdout and writes per-stage logs, `summary.tsv`, `junit.xml`, and `report.md` into `target/verify/`.

```bash
# Fast pre-commit gate: ruff, mypy, spec-sync, secret-scan, smoke, unit
scripts/verify.sh --quick

# Pre-milestone gate: specific test tiers
scripts/verify.sh --tier smoke,unit,integration,system,security

# Full pre-release gate: lint, mypy, spec-sync, secret-scan, all 8 tiers, coverage
scripts/verify.sh

# Additional modes
scripts/verify.sh --only tests/unit/test_web_app.py
scripts/verify.sh --match "golden" --tier integration
scripts/verify.sh --failed
scripts/verify.sh --status
scripts/verify.sh --report
```

### Coverage Thresholds

The full `scripts/verify.sh` gate runs `pytest tests --cov=src/casper --cov-branch` and enforces:

- **Line coverage:** `>= 90.00%`
- **Branch coverage:** `>= 85.00%`

## 8-Tier Test Layout (`tests/`)

| Tier | Directory | Scope |
|---|---|---|
| `smoke` | `tests/smoke/` | Architecture rank DAG (`test_architecture.py`), ADR parity (`test_adr.py`), brand sync (`test_brand.py`), CLI boot (`test_cli_boot.py`), repo hygiene & relative links (`test_hygiene.py`), spec sync (`test_spec.py`), verify gate (`test_verify_gate.py`) |
| `unit` | `tests/unit/` | Module-level tests for `catalog`, `conformance`, `errors`, `facts`, `layers`, `libraries`, `loaders`, `modalities`, `planner`, `profile`, `realizer`, `validator`, `web` |
| `integration` | `tests/integration/` | Cross-module determinism (`test_determinism.py`), 11-combo golden matrix (`test_golden.py`), CLI backend integration (`test_llm.py`), Hypothesis property tests (`test_properties.py`) |
| `system` | `tests/system/` | End-to-end CLI (`test_cli_e2e.py`), surface parity (`test_surface_parity.py`), real-socket Web UI E2E (`test_web_e2e.py`) |
| `security` | `tests/security/` | Global constraints (`test_constraints.py`), zero-invention fidelity (`test_fidelity.py`), loader SSRF/traversal/zip-bomb guards (`test_loaders_security.py`), `.local.yaml` privacy (`test_privacy.py`), HTTP security headers/bounds (`test_web_security.py`) |
| `perf` | `tests/perf/` | Latency budgets (`test_latency_budgets.py`) |
| `stress` | `tests/stress/` | Realizer candidate/size bounds (`test_realizer_bounds.py`), web concurrency (`test_web_concurrency.py`) |
| `torture` | `tests/torture/` | Atomic save crash recovery (`test_atomic_save.py`), loader fault injection (`test_loader_faults.py`), web socket/protocol faults (`test_web_faults.py`) |

## Offline Network Guard & `@pytest.mark.loopback`

[`tests/conftest.py`](../tests/conftest.py) installs an `autouse=True` fixture (`_offline_socket_guard`) that monkeypatches `socket.socket.connect`, `socket.socket.connect_ex`, and `socket.create_connection` to raise `RuntimeError` on any outbound network attempt (`AF_UNIX` remains allowed).

Real-socket end-to-end tests against `127.0.0.1` / `::1` / `localhost` must opt in explicitly with `@pytest.mark.loopback`.

## Fake CLI Writer (`tests/fakes/fake_agent.py`)

[`tests/fakes/fake_agent.py`](../tests/fakes/fake_agent.py) is an offline test double for `claude` and `agy` driven by `CASPER_FAKE_MODE` across **9 modes**:

| `CASPER_FAKE_MODE` | Behavior |
|---|---|
| `good` | Emits valid grounded sentences citing each `[fNNN]` fact ID |
| `reword` | Applies benign lexical rewording while keeping polarity and citations |
| `invent` | Injects an ungrounded metric (`$999,999`) to trigger validator rejection |
| `rename` | Injects an ungrounded proper noun (`ZorgCorp`) to trigger validator rejection |
| `polarity` | Inverts sentence polarity (`on track` → `blocked`) |
| `uncited` | Omits `[fNNN]` citation on the first sentence |
| `empty` | Outputs whitespace only |
| `fail` | Exits non-zero (`1`) simulating auth/CLI failure |
| `hang` | Sleeps for `CASPER_FAKE_SLEEP` seconds (default `5.0`) to exercise timeouts |

Set `CASPER_FAKE_DUMP_PROMPT=<path>` to inspect the exact prompt passed to the CLI writer (e.g., to verify private `.local.yaml` data is absent).

## Golden Output Regeneration

[`tests/integration/test_golden.py`](../tests/integration/test_golden.py) compares all 11 valid `structure × modality` pairs against [`tests/golden/`](../tests/golden). After intentional output changes, regenerate golden snapshots with:

```bash
CASPER_UPDATE_GOLDEN=1 .venv/bin/pytest tests/integration/test_golden.py -q
```

## Sync & Hygiene Checks

Run these deterministic drift and hygiene checks whenever editing specs, brand generators, examples, or docs:

```bash
# Spec compilation sync (spec/0[0-9]-*.md -> SPEC.md)
.venv/bin/python scripts/build_spec.py --check

# Brand asset sync (docs/brand/ + src/casper/web/static/img/)
.venv/bin/python scripts/build_brand.py --check

# Worked examples sync (examples/edge-migration-status.md -> examples/outputs/)
.venv/bin/python scripts/build_examples.py --check

# Secret & machine-specific path scan
bash scripts/scan_secrets_and_paths.sh
```
