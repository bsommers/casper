# 00 — Overview, Architecture & Global Constraints

## 1. Goal

Build **Casper**, a local-first, deterministic ghostwriting toolkit exposed uniformly as a Python library, a CLI (`casper`), and a localhost-only web application (`casper serve`). Casper transforms unstructured or semi-structured source notes into audience-adapted, format-compliant drafts written in a named author's measured voice, with every non-closing sentence traceable to explicit source facts and verified by automated fidelity checks.

## 2. Motivation (Measured)

Baseline measurements carried forward from the draft specification establish the exact problems v1 must solve and the boundaries it must respect:

| Measurement | Observed Baseline | Design Consequence in This Spec |
|---|---|---|
| Held-out author voice calibration (4 articles, leave-one-out) | **74–87 / 100** on held-out articles vs. **18–61 / 100** on out-of-register text (chat, legalese, README, spec) | Retain 32-feature profile-relative scorer (ADR 0006) with provisional bands `80 / 65 / 45` and explicit confidence tiers (`<250` low, `250–999` medium, `≥1000` high). |
| Same-house-style peer authors | **74–91 / 100** (overlaps target author) | Document single-author limitation; defer catalog-relative scoring (ADR 0007) until `≥3` distinct authors exist in `authors/`. |
| Rule-based writer voice scores across 5 saved examples | **31–35 / 100** (longest article **34.6**; deliberately casual draft **25**) | Place `REWRITE_RULES` in shared foundation module `rewrites.py` (ADR 0012) so richer rule rewrites can be added safely without hidden validator coupling, and provide opt-in `claude` and `agy` CLI writers (ADR 0010). |
| Heuristic `ask` misclassification | `"The team will review the plan."` misclassified as `ask` via `"review"` cue, injecting an unsolicited closing CTA | Remove `"review"` from ask cues; require explicit key/heading, inline tag (`[ask]`), or second-person/modal request pattern; expose pre-write fact extraction (`extract_facts`). |
| Offline test suite performance | **195 tests in ~15 s** (baseline target; zero network, zero live LLM calls) | Organize exhaustive pre-build cases across tiered suites (`tests/<tier>/`) gated by `scripts/verify.sh` with a `<20 s` budget for `smoke+unit+integration+system+security`. |
| Live `claude` / `agy` CLI fidelity | **0 live automated runs** (previously fake-CLI only) | Enforce strict automated testing against `tests/fakes/fake_agent.py` (9 modes including polarity flip) plus an explicit opt-in manual live CLI smoke check. |

## 3. Current → Proposed Architecture

**Current state:** Empty greenfield repository containing only `raw_inputs/` and `spec/` (`src/`, `tests/`, `docs/` are empty).

**Proposed architecture:** Strict downward-only layered DAG. Surfaces never own business logic; all 10 domain operations route through a single typed command layer (`commands.py`). `cli.py` invokes `web.server.make_server(...)` directly for `serve` so `commands.py` never imports `web/`.

```text
Rank 8 (Entrypoints)    cli.py                              web/server.py + web/static/
                           |    \                                 |
                           |     +---> web/server.py (serve only) |
                           v                                      v
Rank 7 (Uniform Core)   commands.py (10 typed domain operations; single validation & gating path)
                                                |
Rank 6 (Orchestration)  pipeline.py (generate(Brief) -> Result + ReproducibilityRecord)
                                                |
Rank 5 (Writers/Check)  realizer.py       llm.py (claude|agy)       validator.py
                                                |
Rank 4 (Planning/Fmt)   planner.py        modalities.py             catalog.py
                                                |
Rank 3 (Analysis)       facts.py          conformance.py            layers.py
                                                |
Rank 2 (Extraction)     features/*        profile.py                loaders/*
                                                |
Rank 1 (Foundation)     models.py · errors.py · documents.py · parsing.py · libraries.py · rewrites.py
                                                |
Data Assets             src/casper/data/{personas,structures,modalities,glossaries}/*.yaml
                        src/casper/data/{phrasebank,lexicons}.yaml
                        authors/<id>.yaml + <id>.curated.yaml + <id>.local.yaml (gitignored, 0600)
```

### Strict Module Rank DAG (Enforced by `TC-005`)

Every import `A -> B` within `src/casper/` must satisfy `rank(A) > rank(B)` (with explicit peer imports listed below):

| Rank | Modules | Allowed Same-Rank Imports |
|---:|---|---|
| **1** | `errors`, `models`, `documents`, `parsing`, `libraries`, `rewrites` | `models -> errors`; `documents -> models, errors`; `libraries -> models, errors`; `rewrites -> models`; `parsing -> errors` |
| **2** | `loaders.*`, `features.*`, `profile` | `profile -> loaders, features` |
| **3** | `layers`, `conformance`, `facts` | `conformance -> layers` (pins helper only) |
| **4** | `catalog`, `planner`, `modalities` | None |
| **5** | `realizer`, `llm`, `validator` | `llm -> realizer` (`fit_to_limits`, `substitute` only); **`validator` MUST NEVER import `realizer` or `llm`** |
| **6** | `pipeline` | None |
| **7** | `commands` | None (**MUST NEVER import `cli` or `web`**) |
| **8** | `web.server`, `cli`, `__init__` | `cli -> web.server` (`make_server` for `casper serve` only) |

### Architectural Rules

1. **Acyclic downward dependencies:** Higher ranks import lower ranks only (`TC-005`).
2. **Typed stage seams:** Each stage accepts typed objects and returns the next (`Document` → `FactModel` → `Plan` → `AdaptedPlan` → `Draft` → `Validation` → formatted `str` → `Result`).
3. **YAML for tunable behavior:** Personas, structures, modalities, glossaries, phrasebank, and lexicons live in YAML under `src/casper/data/` and can be overridden per project in `<project_dir>/`.
4. **Hard guarantees vs. quality signals:** Contract guarantees are validator **errors** (`Validation.ok = False`); stylistic/audience signals are **warnings**. `pipeline.generate` and `commands.write_draft` **always** return `Result` (never raise on validation failure); `cli.py` maps `not result.validation.ok` to exit code `1`.
5. **Explicit opt-in for external execution:** Nothing leaves the local machine by default. `claude` and `agy` CLI backends require explicit opt-in and fall back gracefully to `rules` unless `fallback=False`.
6. **Single-path uniform surfaces:** Python public API (`casper.*`), CLI (`cli.py`), and HTTP API (`web/server.py`) invoke the exact same 10 typed commands in `commands.py`.

## 4. Global Constraints (Invariants)

| ID | Invariant | Enforcement Mechanism |
|---|---|---|
| **GC-01** | **No Hugging Face or Python LLM client SDKs.** Forbidden packages: `transformers`, `datasets`, `huggingface-hub`, `huggingface_hub`, `torch`, `openai`, `anthropic`, `google-genai`, `google-generativeai`, `litellm`, `langchain`, `llama-index`. Opt-in exception: subprocess calls to `claude` or `agy` CLI only. | `tests/security/test_constraints.py` (scans `pyproject.toml`, lockfiles, and all `src/` AST imports) |
| **GC-02** | **Pinned runtime stack.** Python `>=3.11,<3.14`; runtime dependencies strictly limited to `spacy` (+ pinned `en_core_web_sm` wheel), `scikit-learn`, `networkx`, `pyyaml`, `beautifulsoup4`, `lxml`, `pypdf`, `python-docx`, `striprtf`. Dev/build tools: `pytest`, `pytest-cov`, `ruff`, `mypy`, `hypothesis`, `pillow` (dev/brand-build only, for PNG/ICO rasterization & dimension verification in `scripts/build_brand.py`). | `pyproject.toml` + `tests/security/test_constraints.py` |
| **GC-03** | **Byte-identical determinism (rules backend).** Same inputs, resolved profile, libraries, and `seed` produce byte-identical `Result.text`, `Result.fact_trace`, and `Result.record.record_sha256`. | `tests/integration/test_determinism.py` |
| **GC-04** | **Zero-invention fact traceability.** Every non-frame sentence cites `≥1` valid `Fact.id`; every signed/unsigned numeric token appears in its cited facts; frame sentences cite zero facts and assert nothing. | `validator.py` + `tests/unit/test_validator.py` + `tests/security/test_fidelity.py` |
| **GC-05** | **Strict privacy boundary.** Author email, consent, and `.local.yaml` content never appear in git-tracked files, never enter `claude`/`agy` prompts, and `.local.yaml` is created atomically with `os.open(..., 0o600)`. | `tests/security/test_privacy.py` + `scripts/scan_secrets_and_paths.sh` |
| **GC-06** | **Localhost-only web binding & SSRF guard.** `web/server.py` binds exclusively to `127.0.0.1`; `loaders` URL fetches reject non-HTTP(S) schemes and private/loopback/link-local/reserved IPs on initial fetch and every redirect hop. | `tests/security/test_web_security.py`, `tests/security/test_loaders_security.py` |
| **GC-07** | **Zero external network in default test suite.** Running `scripts/verify.sh` performs zero outbound DNS/HTTP connections and zero live LLM calls. | `tests/conftest.py` socket guard (loopback allowed only for real-socket E2E test) |
| **GC-08** | **Zero external brand leakage.** No third-party brand names appear anywhere in code, specs, tests, examples, or docs. | `tests/smoke/test_hygiene.py` |
| **GC-09** | **Clean-clone green.** All verification suites pass on a fresh checkout with `input/`, `output/`, and `target/` empty. | `scripts/verify.sh` |
| **GC-10** | **No silent skips or lowered bars.** Zero warnings under `ruff check .` and `mypy src/`; coverage tripwire `≥90%` line and `≥85%` branch on `src/casper/`; every skipped test must print a reason and count toward skip reporting. | `scripts/verify.sh` |

## 5. Architecture Decision Register (ADRs)

ADRs live in `docs/adr/NNNN-slug.md` (created from `docs/adr/TEMPLATE.md`), are append-only, and are checked for index parity by `tests/smoke/test_adr.py`.

| ADR | Decision | Status | Enforced By |
|---|---|---|---|
| **0001** | No in-process LLM or Hugging Face; deterministic rule-based realization default (amended by 0010) | accepted | `tests/security/test_constraints.py` |
| **0002** | Author profiles stored as one YAML file per author in `authors/` | accepted | `tests/unit/test_profile.py` |
| **0003** | Root `SPEC.md` deterministically generated from `spec/0[0-9]-*.md` via `scripts/build_spec.py` | accepted | `tests/smoke/test_spec.py` |
| **0004** | `input/` and `output/` git-ignored (keeping `README.md` placeholders) | accepted | `.gitignore` + `tests/smoke/test_hygiene.py` |
| **0005** | Three-layer author profiles (`<id>.yaml`, `.curated.yaml`, `.local.yaml` mode `0600`) with tamper guard | accepted | `tests/unit/test_layers.py`, `tests/security/test_privacy.py` |
| **0006** | Profile-relative, deterministic 32-feature voice conformance score | accepted | `tests/unit/test_conformance.py` |
| **0007** | Catalog-relative voice scoring once `≥3` distinct authors exist in `authors/` | proposed | Deferred until catalog has `≥3` authors |
| **0008** | v1 library scope: 10 personas, 3 structures, 5 modalities, 1 default glossary | accepted | `tests/unit/test_libraries.py` |
| **0009** | Every non-frame sentence cites facts; candidate variants ranked by voice score | accepted | `tests/unit/test_realizer.py`, `tests/unit/test_validator.py` |
| **0010** | Optional `claude` and `agy` CLI writers behind explicit opt-in and automatic fallback | accepted | `tests/integration/test_llm.py` |
| **0011** | Web interface is a localhost-only Python standard-library `ThreadingHTTPServer` + frameworkless static UI | accepted | `tests/security/test_web_security.py`, `tests/system/test_web_e2e.py` |
| **0012** | Shared `rewrites.py` token declarations, tightened `ask` cues with inline `[kind]` overrides, dual `FidelityMode` (`strict` vs. `assisted` with per-fact polarity check), and deterministic Casper ghost brand kit | accepted | `tests/unit/test_facts.py`, `tests/unit/test_realizer.py`, `tests/unit/test_validator.py`, `tests/smoke/test_brand.py` |

## 6. Resolutions of Draft Architecture Review Items

1. **Draft §12.1 — Voice vs. Facts (Rewrite Space):** v1 ships both deterministic `RuleBasedRealizer` and optional `CliAgentRealizer` (`claude`/`agy`). `rewrites.py` defines an explicit `RewriteRule` registry from day one so future voice levers can be added safely.
2. **Draft §12.2 — Fact Classification & Closing CTA Trigger:** Drop `"review"` from `_CUES["ask"]`; require explicit key/heading, inline tag (`[ask]`..`[detail]`), or second-person/modal request wording; expose `extract_facts` (`--dry-run` / `POST /api/extract`) and `fact_overrides`; emit closing CTA frames only when `≥1` kept fact has `kind == FactKind.ASK`.
3. **Draft §12.3 — Two Writers, Two Guarantees:** Formalize `FidelityMode.STRICT` (`rules`) vs. `FidelityMode.ASSISTED` (`claude`/`agy`). `ASSISTED` enforces `untraced`, `unknown-fact`, `frame-with-facts`, `unsupported-number` (signed), `unsupported-name` (including sentence-initial proper nouns), and `polarity-mismatch` (per-fact negation & antonym flip) as hard `ERROR`s; lexical rewording emits `reworded` warning.
4. **Draft §12.4 — Eliminate Writer/Validator Hidden Coupling:** Place `REWRITE_RULES` in `src/casper/rewrites.py` (Rank 1). Both `realizer.py` and `validator.py` import downward from `rewrites.py`; `validator.py` never imports `realizer.py` (`TC-005`).
5. **Draft §12.5 — Single-Author Voice Scoring:** Profile-relative scoring (ADR 0006) ships in v1 with confidence badges and documented house-style overlap; catalog-relative scoring (ADR 0007) activates once `≥3` distinct authors exist.
6. **Intentional Omissions from Draft:** `scripts/capture_screenshots.mjs` and standalone print `brochure` are deferred out of v1 core build scope (no Node/Playwright runtime required for offline Python verification); visual identity is delivered deterministically in Python via `scripts/build_brand.py` (`05-brand-assets.md`).

## 7. Repository Layout

```text
casper/
├── pyproject.toml                  # Hatchling build; console script `casper = casper.cli:main`; ruff/mypy/pytest config
├── .gitignore                      # .venv, caches, target/, input/*, output/* (keep README.md), authors/*.local.yaml, *.bak, *.tmp
├── AGENTS.md                       # Agent quickstart + scripts/verify.sh one-line contract
├── README.md                       # Quickstart, brand hero banner, architecture overview
├── SPEC.md                         # Generated from spec/0[0-9]-*.md by scripts/build_spec.py
├── spec/
│   ├── README.md
│   ├── 00-overview.md .. 05-brand-assets.md
│   └── build-specification.md      # Preserved original draft
├── src/casper/
│   ├── __init__.py                 # Lazy public exports wrapping commands.py + models + errors
│   ├── errors.py                   # Typed exception hierarchy + exit/HTTP codes
│   ├── models.py                   # All dataclasses, enums, JSON to_dict() helpers
│   ├── rewrites.py                 # Shared RewriteRule registry + added_tokens catalog (Rank 1)
│   ├── documents.py                # Document & Block helpers, canonical prose extraction
│   ├── parsing.py                  # Cached spaCy load_nlp(ner=False|True)
│   ├── libraries.py                # load_libraries, project_dir overlay, check_combo, digest
│   ├── loaders/                    # __init__.py, html.py, markdown.py, latex.py, docx.py, pdf.py, rtf.py, office.py, tabular.py
│   ├── features/                   # __init__.py, sentences.py, lexical.py, voice.py, structure.py, signature.py, stability.py
│   ├── profile.py                  # build_profile, save_profile (atomic + tamper guard), load_profile, style_guide
│   ├── layers.py                   # resolve, load_resolved_profile, drift_report, write_local_email (0600 atomic)
│   ├── conformance.py              # 32-feature scorer + geometric mean + structure dim + gap explanations
│   ├── catalog.py                  # list_authors, find_profile, diff_authors
│   ├── facts.py                    # ingest, inline tags, tightened cues, salience, NetworkX DiGraph
│   ├── planner.py                  # plan_structure, adapt
│   ├── modalities.py               # plain, html, markdown, slack lossless formatters + word/char counter
│   ├── realizer.py                 # RuleBasedRealizer, fit_to_limits, substitute
│   ├── llm.py                      # CliAgentRealizer (claude, agy), prompt builder, parser, status()
│   ├── validator.py                # STRICT & ASSISTED validator, per-fact polarity check, persona/voice checks
│   ├── pipeline.py                 # generate(), fact_trace, ReproducibilityRecord
│   ├── commands.py                 # Uniform core dispatcher (10 typed operations)
│   ├── cli.py                      # `casper` CLI adapter
│   ├── data/
│   │   ├── personas/*.yaml         # 10 shipped personas
│   │   ├── structures/*.yaml       # 3 shipped structures
│   │   ├── modalities/*.yaml       # 5 shipped modalities
│   │   ├── glossaries/default.yaml # 1 shipped glossary
│   │   ├── phrasebank.yaml         # Closing lines keyed by cta_style
│   │   └── lexicons.yaml           # transitions, intensifiers, hedges, negations, function_words (60)
│   └── web/
│       ├── __init__.py
│       ├── server.py               # Pure App.handle() + localhost ThreadingHTTPServer
│       └── static/                 # index.html, app.js, theme.css, img/* (byte-synced from docs/brand/)
├── authors/                        # Tracked <id>.yaml & <id>.curated.yaml; <id>.local.yaml gitignored
├── examples/                       # Sample input notes + expected outputs/
├── docs/
│   ├── adr/                        # README.md, TEMPLATE.md, 0001..0012-*.md
│   ├── brand/                      # Cute ghost logos, favicons, icons/, stickers/, wallpapers/ (up to 3480x1440)
│   ├── data-model.md
│   ├── api-reference.md
│   ├── using.md
│   └── testing.md
├── scripts/
│   ├── verify.sh                   # Silent-on-success tiered verification gate
│   ├── start.sh                    # uv venv bootstrap + localhost server start (PID: target/casper.pid)
│   ├── stop.sh                     # PID-verified graceful stop
│   ├── build_spec.py               # Deterministic spec/0[0-9]-*.md -> SPEC.md compiler
│   ├── build_brand.py              # Deterministic cute ghost SVG/PNG/ICO/sticker/wallpaper generator + static sync
│   ├── build_examples.py           # Deterministic examples/outputs/ regenerator
│   ├── calibrate_conformance.py    # Leave-one-out conformance calibration script
│   └── scan_secrets_and_paths.sh   # Privacy & machine-path leak scanner
├── tests/
│   ├── conftest.py                 # Offline socket guard, shared fixtures
│   ├── fixtures/                   # Synthetic test author corpus, status_notes.md, sample HTML/MD/LaTeX/RTF/PDF/DOCX/CSV/YAML
│   ├── fakes/fake_agent.py         # Deterministic fake claude/agy CLI (9 modes)
│   ├── golden/                     # 11 golden outputs bound exclusively to tests/fixtures/
│   ├── smoke/ unit/ integration/ system/ perf/ stress/ torture/ security/
├── input/README.md
└── output/README.md
```
