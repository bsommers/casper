# 04 — Dependency-Ordered Implementation & Verification Plan

Every task below follows RED → GREEN → VERIFY, depends strictly on earlier tasks (zero forward dependencies), and ends in a clean, committable state.

## 1. Dependency-Ordered Build Tasks

### Task 1: Repository Scaffold, Packaging, ADR/Spec Machinery & Verification Gate
**Depends on:** None  
**Files:** create `pyproject.toml`, `.gitignore`, `AGENTS.md`, `input/README.md`, `output/README.md`, `docs/adr/TEMPLATE.md`, `docs/adr/README.md`, `docs/adr/0001..0012-*.md`, `scripts/build_spec.py`, `scripts/scan_secrets_and_paths.sh`, `scripts/verify.sh`, `tests/conftest.py`, `tests/smoke/test_spec.py`, `tests/smoke/test_adr.py`, `tests/smoke/test_hygiene.py`, `tests/smoke/test_architecture.py`, `tests/smoke/test_verify_gate.py`, `tests/security/test_constraints.py`, `src/casper/__init__.py`  
**Produces:** Installable `casper` package skeleton, `SPEC.md` compiler (`spec/0[0-9]-*.md` → `SPEC.md`), ADR register, offline socket guard, AST Rank 1..8 DAG check, and `scripts/verify.sh` one-line gate.
- [ ] Write failing tests `TC-002`, `TC-003`, `TC-004` (phased: checks `.gitignore`, existing links, zero external brand strings; brand-sync check activates once `docs/brand/` exists in Task 14), `TC-005`, `TC-028`, `TC-049` (guarded with `CASPER_IN_VERIFY=1` to prevent recursion).
- [ ] Create `pyproject.toml` (Python 3.11–3.13, pinned runtime deps, dev extras incl. `pillow` for brand PNG/ICO generation, hatchling wheel, `casper = casper.cli:main`, ruff/mypy/pytest settings), `.gitignore`, `AGENTS.md`, ADRs `0001`–`0012`, `scripts/build_spec.py`, `scripts/scan_secrets_and_paths.sh`, and `scripts/verify.sh`.
- [ ] Run `scripts/build_spec.py` to generate `SPEC.md` and verify: `scripts/verify.sh --quick` → `PASS`.

### Task 2: Core Data Models, Typed Errors, Shared Rewrite Rules, spaCy Parsing & Loaders
**Depends on:** Task 1  
**Files:** create `src/casper/errors.py`, `src/casper/models.py`, `src/casper/rewrites.py`, `src/casper/documents.py`, `src/casper/parsing.py`, `src/casper/loaders/{__init__,html,markdown,latex,docx,pdf,rtf,office,tabular}.py`, `tests/fixtures/*`, `tests/unit/test_loaders.py`, `tests/security/test_loaders_security.py`, `tests/torture/test_loader_faults.py`  
**Produces:** All dataclasses/enums with `to_dict()`, `CasperError` hierarchy, Rank-1 `REWRITE_RULES` + `ALLOWED_RULE_TOKENS`, `load_nlp(ner=...)`, uniform `load_document` / `load_bytes` (including CSV, YAML, `Key: value` block preservation, HTML `SUMMARY`/`AUDIENCE`/`RESOURCES` tagging, SSRF IP+redirect guard, DOCX zip-bomb cap), `collect_input_paths`.  
**Consumes:** Task 1 package scaffold.
- [ ] Write failing tests `TC-006`, `TC-024`, `TC-034`, `TC-043`, `TC-044`.
- [ ] Implement `errors.py`, `models.py`, `rewrites.py`, `documents.py`, `parsing.py`, and `loaders/`.
- [ ] Verify: `scripts/verify.sh --only unit/test_loaders security/test_loaders_security torture/test_loader_faults smoke/test_architecture` → `PASS`.

### Task 3: Shipped YAML Libraries & Validation
**Depends on:** Task 2  
**Files:** create `src/casper/data/personas/*.yaml` (10), `src/casper/data/structures/*.yaml` (3), `src/casper/data/modalities/*.yaml` (5), `src/casper/data/glossaries/default.yaml`, `src/casper/data/phrasebank.yaml`, `src/casper/data/lexicons.yaml`, `src/casper/libraries.py`, `tests/unit/test_libraries.py`, `tests/unit/test_errors.py`  
**Produces:** `load_libraries(project_dir=None) -> Libraries`, `check_combo(...)`, deterministic `Libraries.digest`.  
**Consumes:** `models.py`, `errors.py`.
- [ ] Write failing tests `TC-010` and library-error cases of `TC-035` in `tests/unit/test_errors.py`.
- [ ] Author all shipped YAML assets per `01-data-model.md §6` and implement `libraries.py` with `(kind, id)` persona keying, `project_dir` overrides, and referential validation.
- [ ] Verify: `scripts/verify.sh --only unit/test_libraries unit/test_errors` → `PASS`.

### Task 4: Linguistic Feature Extractors & Author Profile Builder
**Depends on:** Task 2, Task 3  
**Files:** create `src/casper/features/{__init__,sentences,lexical,voice,structure,signature,stability}.py`, `src/casper/profile.py`, `tests/unit/test_profile.py`, `tests/torture/test_atomic_save.py`  
**Produces:** `STABILITY_KEYS` (32), `features.analyze` (all 11 feature groups per `01-data-model.md §4.1`), `render_style_guide` (8 areas), `build_profile`, `compute_body_sha256`, `check_profile_writable`, `save_profile` (atomic), `load_profile`.  
**Consumes:** `loaders`, `parsing.load_nlp(ner=False)`, `libraries` (`lexicons.yaml`).
- [ ] Write failing tests `TC-007`, `TC-021`, `TC-038` (profile atomic save), `TC-045` (crash recovery).
- [ ] Implement the 6 feature extractor modules and `profile.py`.
- [ ] Verify: `scripts/verify.sh --only unit/test_profile torture/test_atomic_save` → `PASS`.

### Task 5: Three-Layer Profile Resolution, Tamper Guard & Privacy Controls
**Depends on:** Task 4  
**Files:** create `src/casper/layers.py`, `tests/unit/test_layers.py`, `tests/security/test_privacy.py`, update `tests/unit/test_errors.py`  
**Produces:** `layers.resolve` (stripping `overlays`), `load_resolved_profile`, `drift_report`, atomic `0o600` `write_local_email`.  
**Consumes:** `profile.py`, `STABILITY_KEYS`.
- [ ] Write failing tests `TC-008`, `TC-030` (atomic `0600` local email & tracked-file isolation), `TC-031`, `TC-036`, and layer plain-list rejection in `TC-035` (`test_errors.py`).
- [ ] Implement `layers.py` using `os.open(..., os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)` for `.local.yaml`.
- [ ] Verify: `scripts/verify.sh --only unit/test_layers unit/test_errors security/test_privacy` → `PASS`.

### Task 6: Voice Conformance Scorer & Calibration Script
**Depends on:** Task 4, Task 5  
**Files:** create `src/casper/conformance.py`, `scripts/calibrate_conformance.py`, `tests/unit/test_conformance.py`  
**Produces:** `conformance.score(profile, document, nlp=None) -> ConformanceReport` (incl. exact `structure` heading-density & heading-case-style formulas) and leave-one-out calibration script.  
**Consumes:** `features.analyze`, `STABILITY_KEYS`, `layers` pins.
- [ ] Write failing tests `TC-009`, `TC-022`.
- [ ] Implement `conformance.py` and `scripts/calibrate_conformance.py`.
- [ ] Verify: `scripts/verify.sh --only unit/test_conformance` → `PASS`.

### Task 7: Author Catalog & Diffing
**Depends on:** Task 5, Task 6  
**Files:** create `src/casper/catalog.py`, `tests/unit/test_catalog.py`  
**Produces:** `list_authors`, `find_profile(..., allow_path=True|False)` (`SecurityError` on invalid/path ID, `ProfileNotFoundError` on missing valid ID), `diff_authors` (normalized delta formula).  
**Consumes:** `profile.py`, `layers.py`, `STABILITY_KEYS`.
- [ ] Write failing tests `TC-015` plus catalog-ID traversal (`SecurityError`) & missing-ID (`ProfileNotFoundError`) tests.
- [ ] Implement `catalog.py`.
- [ ] Verify: `scripts/verify.sh --only unit/test_catalog` → `PASS`.

### Task 8: Fact Ingestion & NetworkX Fact Graph
**Depends on:** Task 2, Task 3  
**Files:** create `src/casper/facts.py`, `tests/unit/test_facts.py`, update `tests/unit/test_errors.py`  
**Produces:** `facts.ingest(inputs, notes, nlp=None, fact_overrides=None) -> FactModel`.  
**Consumes:** `loaders.load_document`, `parsing.load_nlp(ner=True)`, `models.Fact/FactModel`.
- [ ] Write failing tests `TC-011`, `TC-020` (non-ask `"review"` vs. explicit ask), and empty-input / unknown-`fact_overrides`-ID cases of `TC-035` (`test_errors.py`).
- [ ] Implement `facts.py`: uniform `load_document` ingestion, deduplication before `f001..` ID assignment, inline `[kind]` tags, `Key: value` blocks, `_HEADING_KIND`, tightened `_CUES`, salience formula, and NetworkX `DiGraph`.
- [ ] Verify: `scripts/verify.sh --only unit/test_facts unit/test_errors` → `PASS`.

### Task 9: Structure Planning & Persona Adaptation
**Depends on:** Task 3, Task 8  
**Files:** create `src/casper/planner.py`, `tests/unit/test_planner.py`  
**Produces:** `plan_structure`, `adapt`.  
**Consumes:** `FactModel`, `Structure`, `Persona`, `Glossary`.
- [ ] Write failing tests `TC-012`.
- [ ] Implement `planner.py` per `02-contracts.md §1.8`.
- [ ] Verify: `scripts/verify.sh --only unit/test_planner` → `PASS`.

### Task 10: Modality Formatters & Rule-Based Realizer
**Depends on:** Task 6, Task 9  
**Files:** create `src/casper/modalities.py`, `src/casper/realizer.py`, `tests/unit/test_modalities.py`, `tests/unit/test_realizer.py`, `tests/stress/test_realizer_bounds.py`, `tests/integration/test_properties.py`  
**Produces:** `format_draft`, `count_rendered`, `substitute`, `fit_to_limits(..., modality)`, `RuleBasedRealizer(..., modality)`.  
**Consumes:** `rewrites.REWRITE_RULES` (Rank 1), `AdaptedPlan`, `conformance.score`, `Libraries`, `Constraints`, `Modality`.
- [ ] Write failing tests `TC-013`, `TC-014`, `TC-026` (15-fact direct-index sampling, zero OOM), `TC-027` (Hypothesis properties).
- [ ] Implement lossless `modalities.py` + `count_rendered`, and `realizer.py` with OOM-safe direct-index sampling, per-call parse cache, and `Draft.declared_additions`.
- [ ] Verify: `scripts/verify.sh --only unit/test_modalities unit/test_realizer stress/test_realizer_bounds integration/test_properties` → `PASS`.

### Task 11: Strict & Assisted Fidelity Validator
**Depends on:** Task 6, Task 10  
**Files:** create `src/casper/validator.py`, `tests/unit/test_validator.py`, `tests/security/test_fidelity.py`  
**Produces:** `validator.validate(..., modality, fidelity_mode, glossary)` enforcing all 22 check codes.  
**Consumes:** `rewrites.ALLOWED_RULE_TOKENS` (Rank 1 — NEVER imports `realizer.py`), `modalities.count_rendered`, `conformance.score`, `Draft`, `AdaptedPlan`, `FactModel`, `Constraints`, `Glossary`.
- [ ] Write failing tests `TC-023`, `TC-029` (signed numbers, sentence-initial & mid-sentence proper names, single- & multi-fact polarity flips, benign idiom non-regression, `Draft.title` banned/glossary checks, apostrophe-preserving contractions).
- [ ] Implement `validator.py`.
- [ ] Verify: `scripts/verify.sh --only unit/test_validator security/test_fidelity smoke/test_architecture` → `PASS`.

### Task 12: Optional Claude (`claude`) & Antigravity (`agy`) CLI Writers + Fake CLI
**Depends on:** Task 10, Task 11  
**Files:** create `src/casper/llm.py`, `tests/fakes/fake_agent.py`, `tests/integration/test_llm.py`, update `tests/security/test_privacy.py`  
**Produces:** `CliAgentRealizer` (`claude` & `agy`, accepting `modality`), `llm.status()`, and 9-mode `fake_agent.py`.  
**Consumes:** `realizer.fit_to_limits`, `realizer.substitute`, `AdaptedPlan`, `Constraints`, `Modality` (`tests/integration/test_llm.py` validates outputs via `validator.validate(fidelity_mode=ASSISTED)`; `llm.py` itself NEVER imports `validator.py`).
- [ ] Write failing tests `TC-041`, `TC-042`, and prompt-privacy checks in `TC-030` across both `claude` and `agy`.
- [ ] Implement `tests/fakes/fake_agent.py` (`good`, `invent`, `rename`, `polarity`, `uncited`, `reword`, `fail`, `empty`, `hang`) and `src/casper/llm.py`.
- [ ] Verify: `scripts/verify.sh --only integration/test_llm security/test_privacy smoke/test_architecture` → `PASS`.

### Task 13: Pipeline, Reproducibility Record, Uniform Command Dispatcher & CLI
**Depends on:** Task 7, Task 11, Task 12  
**Files:** create `src/casper/pipeline.py`, `src/casper/commands.py`, `src/casper/cli.py`, update `src/casper/__init__.py`, create `tests/golden/*` (bound strictly to synthetic `tests/fixtures/`), `tests/smoke/test_cli_boot.py`, `tests/integration/test_golden.py`, `tests/integration/test_determinism.py`, `tests/system/test_cli_e2e.py`, `tests/perf/test_latency_budgets.py`, update `tests/unit/test_errors.py` & `tests/security/test_privacy.py`  
**Produces:** `pipeline.generate`, `commands.py` (exact 10 operations), `casper` CLI (incl. `--authors-dir`, `--fact-override`, `--json`, `serve` flags), lazy `casper.*` exports, and 11 synthetic-fixture golden outputs.  
**Consumes:** All stages from Tasks 2–12.
- [ ] Write failing tests `TC-001`, `TC-016`, `TC-018`, `TC-037`, `TC-047`, plus unknown-backend & `--raw --overlay` cases in `TC-035` (`test_errors.py`) and CLI `--email` privacy test in `TC-030` (`test_privacy.py`).
- [ ] Implement `pipeline.py`, `commands.py`, `cli.py`, and `__init__.py`. Generate verified `tests/golden/` from `tests/fixtures/` with `CASPER_UPDATE_GOLDEN=1`.
- [ ] Verify: `scripts/verify.sh --only smoke/test_cli_boot integration/test_golden integration/test_determinism system/test_cli_e2e perf/test_latency_budgets unit/test_errors security/test_privacy` → `PASS`.

### Task 14: Super-Cute Ghost Brand Kit, Localhost Web Server, Static UI & Surface Parity
**Depends on:** Task 13  
**Files:** create `scripts/build_brand.py`, `docs/brand/*` (logos, favicons, `icons/*`, `stickers/*`, `wallpapers/*` up to `3480x1440` per `05-brand-assets.md`), `src/casper/web/{__init__,server}.py`, `src/casper/web/static/{index.html,app.js,theme.css,img/*}`, `tests/smoke/test_brand.py`, `tests/unit/test_web_app.py`, `tests/security/test_web_security.py`, `tests/system/test_web_e2e.py`, `tests/system/test_surface_parity.py`, `tests/stress/test_web_concurrency.py`, `tests/torture/test_web_faults.py`  
**Produces:** Complete deterministic super-cute ghost brand kit (logos, icons, die-cut stickers with border cutouts, wallpapers up to `3480x1440`), pure `App.handle()`, hardened localhost `ThreadingHTTPServer`, frameworkless static UI (chips, 3 result views, Copy/Download, fact inspector, backend badges), and cross-surface parity tests.  
**Consumes:** `commands.py` (with `allow_author_path=False`).
- [ ] Write failing tests `TC-017`, `TC-019`, `TC-025`, `TC-032`, `TC-033`, `TC-039`, `TC-046`, `TC-050`.
- [ ] Implement `scripts/build_brand.py` (generates all `05-brand-assets.md` deliverables deterministically and syncs web subset to `src/casper/web/static/img/`), `web/server.py`, and `web/static/`.
- [ ] Run `scripts/build_brand.py` and verify: `scripts/verify.sh --only smoke/test_brand smoke/test_hygiene unit/test_web_app security/test_web_security system/test_web_e2e system/test_surface_parity stress/test_web_concurrency torture/test_web_faults` → `PASS`.

### Task 15: Operational Scripts, Examples, Documentation Suite & Full Release Gate
**Depends on:** Task 14  
**Files:** create `scripts/start.sh`, `scripts/stop.sh`, `scripts/build_examples.py`, `examples/edge-migration-status.md`, `examples/outputs/*`, `authors/bill.yaml` (built from clean synthetic/provided sample corpus, zero private email), `README.md`, `docs/{data-model,api-reference,using,testing}.md`, `tests/system/test_scripts.py`, `tests/system/test_examples.py`  
**Produces:** Operational scripts (`target/casper.pid`), reproducible worked examples, synced documentation suite, and green full-tier verification.  
**Consumes:** `casper` CLI and `web/server.py`.
- [ ] Write failing tests `TC-040`, `TC-048`.
- [ ] Implement `start.sh`, `stop.sh`, `scripts/build_examples.py`, worked examples, and docs (`README.md`, `docs/*.md`).
- [ ] Run `scripts/build_spec.py`, `scripts/build_brand.py`, `scripts/build_examples.py`, and run full Gate 3: `scripts/verify.sh` → `PASS`.

## 2. Verification Plan

### Layered Automated Gates (`scripts/verify.sh`)

```bash
# Gate 1 — Pre-commit (lint + typecheck + spec-sync + secret-scan + smoke + unit)
scripts/verify.sh --quick
# Expected: PASS <N>/<N> <S>s skips=0

# Gate 2 — Pre-milestone (all functional + security tiers)
scripts/verify.sh --tier smoke,unit,integration,system,security
# Expected: PASS <N>/<N> <S>s skips=0  (target runtime < 20s)

# Gate 3 — Pre-release (all 8 tiers + coverage tripwire >=90% line / >=85% branch)
scripts/verify.sh
# Expected: PASS <N>/<N> <S>s skips=0
```

### Direct End-to-End Smoke Verification

```bash
# 1. Spec & Brand asset sync checks
.venv/bin/python scripts/build_spec.py --check
.venv/bin/python scripts/build_brand.py --check

# 2. Localhost server lifecycle + API options round trip
scripts/start.sh --background --port 8742 \
  && curl -sf http://127.0.0.1:8742/api/options | head -c 120 \
  && scripts/stop.sh

# 3. Deterministic CLI generation diff against example golden
.venv/bin/casper write --author bill --source developer --target management \
  --structure status_update --modality slack \
  -i examples/edge-migration-status.md --seed 1 \
  | diff -u - examples/outputs/status-slack.txt

# 4. Clean-clone check
rm -rf target/verify && scripts/verify.sh
```

### Opt-In Live CLI Verification (Manual, Outside Offline CI)

```bash
.venv/bin/casper write --backend-status
.venv/bin/casper write --backend claude --no-fallback --structure status_update --modality slack \
  --source developer --target management -i examples/edge-migration-status.md
.venv/bin/casper write --backend agy --no-fallback --structure status_update --modality slack \
  --source developer --target management -i examples/edge-migration-status.md
```
