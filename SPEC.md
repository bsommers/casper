<!-- DO NOT EDIT DIRECTLY. Generated deterministically by scripts/build_spec.py from spec/0[0-9]-*.md (ADR 0003). -->

# Casper — Complete Technical Specification

## Table of Contents

- `00-overview.md` — 00 — Overview, Architecture & Global Constraints
- `01-data-model.md` — 01 — Core Data Model, Profile Schema & Shipped Libraries
- `02-contracts.md` — 02 — Stage Contracts, Uniform Surfaces & Security Boundaries
- `03-test-matrix.md` — 03 — Pre-Build Exhaustive Test Matrix & Threat Model
- `04-implementation-plan.md` — 04 — Dependency-Ordered Implementation & Verification Plan
- `05-brand-assets.md` — 05 — Casper Super-Cute Ghost Brand & Visual Asset Kit Contract

---

<!-- source: spec/00-overview.md -->

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

---

<!-- source: spec/01-data-model.md -->

# 01 — Core Data Model, Profile Schema & Shipped Libraries

All core types live in `src/casper/models.py`, `src/casper/errors.py`, and `src/casper/rewrites.py`. Every stage consumes and produces these exact types before any implementation begins.

## 1. Enumerations & Constants

```python
from enum import StrEnum

class BlockKind(StrEnum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    QUOTE = "quote"
    CODE = "code"
    SUMMARY = "summary"
    AUDIENCE = "audience"
    RESOURCES = "resources"

EXCLUDED_VOICE_BLOCK_KINDS: frozenset[BlockKind] = frozenset({
    BlockKind.SUMMARY,
    BlockKind.AUDIENCE,
    BlockKind.RESOURCES,
})

class FactKind(StrEnum):
    STATUS = "status"
    PROGRESS = "progress"
    RISK = "risk"
    NEXT_STEP = "next_step"
    DECISION = "decision"
    BACKGROUND = "background"
    DETAIL = "detail"
    METRIC = "metric"
    ASK = "ask"

class PersonaKind(StrEnum):
    SOURCE = "source"
    TARGET = "target"

class DepthLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

DEPTH_CAPS: dict[DepthLevel, int] = {
    DepthLevel.LOW: 1,
    DepthLevel.MEDIUM: 3,
    DepthLevel.HIGH: 6,
}

class JargonLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class MarkupKind(StrEnum):
    MARKDOWN = "markdown"
    SLACK = "slack"
    HTML = "html"
    PLAIN = "plain"

class BackendKind(StrEnum):
    RULES = "rules"
    CLAUDE = "claude"
    AGY = "agy"

class FidelityMode(StrEnum):
    STRICT = "strict"       # BackendKind.RULES
    ASSISTED = "assisted"   # BackendKind.CLAUDE | BackendKind.AGY

class CheckLevel(StrEnum):
    ERROR = "error"
    WARNING = "warning"

class MatchBand(StrEnum):
    STRONG = "strong"       # >= 80
    CLOSE = "close"         # >= 65
    PARTIAL = "partial"     # >= 45
    DIFFERENT = "different" # < 45

class ConfidenceBand(StrEnum):
    HIGH = "high"           # >= 1000 words
    MEDIUM = "medium"       # >= 250 words
    LOW = "low"             # < 250 words
```

## 2. Core Dataclasses (`src/casper/models.py`)

All dataclasses expose `to_dict() -> dict[str, Any]` (converting `StrEnum` → `str`, `tuple`/`frozenset` → sorted `list`, `None` preserved) for deterministic JSON serialization across CLI `--json`, `.trace.json`, and HTTP API responses.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    level: int = 0                  # heading depth (1..6) or list nesting depth
    links: int = 0                  # hyperlink count in block
    emphasis_lead: bool = False     # True if block starts with bold/italic lead-in

@dataclass(frozen=True)
class Document:
    source: str                     # file path, URL, or "<inline>"
    format: str                     # html|markdown|text|latex|docx|pdf|rtf|doc|odt|csv|yaml
    title: str | None = None
    authors: tuple[str, ...] = ()
    published: str | None = None    # ISO-8601 date/datetime string if extracted
    modified: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    blocks: tuple[Block, ...] = ()
    sha256: str = ""                # lowercase hex SHA-256 of raw input bytes
    notes: tuple[str, ...] = ()     # non-fatal loader diagnostics

@dataclass(frozen=True)
class Fact:
    id: str                         # "f001", "f002", ... (regex: ^f\d{3,}$)
    kind: FactKind
    text: str                       # normalized single-sentence/statement text
    source: str                     # Document.source
    order: int                      # 0-based reading order across all inputs
    entities: tuple[str, ...] = ()  # spaCy ORG, PRODUCT, GPE, FAC, EVENT, WORK_OF_ART, LAW
    metrics: tuple[str, ...] = ()   # signed/unsigned numbers with units, percentages, or currency
    dates: tuple[str, ...] = ()     # spaCy DATE/TIME + ISO dates
    owners: tuple[str, ...] = ()    # spaCy PERSON + explicit Owner key
    salience: float = 1.0           # 1.0 + 0.4*bool(metrics) + 0.2*min(len(entities),2) + 0.2*bool(dates) + 0.3*(kind==STATUS)
    classification_source: str = "default"  # override|inline_tag|key|heading|cue|default

@dataclass
class FactModel:
    facts: tuple[Fact, ...]
    graph: Any                      # networkx.DiGraph: nodes (fact/entity/owner/metric/date), edges (mentions, follows)
    input_hashes: dict[str, str]    # source -> sha256
    digest: str                     # SHA-256 of canonical JSON of facts
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class Persona:
    id: str
    kind: PersonaKind
    priorities: tuple[str, ...]
    vocabulary_include: tuple[str, ...]
    vocabulary_avoid: tuple[str, ...]
    detail_depth: DepthLevel
    jargon_level: JargonLevel
    framing_patterns: tuple[str, ...]
    typical_concerns: tuple[str, ...]
    cta_styles: tuple[str, ...]
    section_priority: tuple[str, ...]

@dataclass(frozen=True)
class Section:
    name: str
    purpose: str
    fact_kinds: tuple[FactKind, ...]
    required: bool
    min_words: int
    max_words: int
    heading: str

@dataclass(frozen=True)
class Structure:
    id: str
    goal: str
    sections: tuple[Section, ...]
    compatible_modalities: tuple[str, ...]
    default_target_personas: tuple[str, ...]

@dataclass(frozen=True)
class Modality:
    id: str
    markup: MarkupKind
    max_words: int | None
    max_chars: int | None
    title: bool
    headings: str                   # "none" | "h2" | "bold" | "slack_bold"
    bullets: bool
    description: str

@dataclass(frozen=True)
class Glossary:
    plain: dict[str, str]           # jargon term -> plain replacement
    preferred: dict[str, str]       # discouraged variant -> house form
    banned: tuple[str, ...]         # forbidden terms (case-insensitive whole-word)

@dataclass(frozen=True)
class Libraries:
    personas: dict[tuple[PersonaKind, str], Persona]
    structures: dict[str, Structure]
    modalities: dict[str, Modality]
    glossary: Glossary
    phrasebank: dict[str, tuple[str, ...]]  # cta_style -> closing lines
    lexicons: dict[str, tuple[str, ...]]    # transitions, intensifiers, hedges, negations, function_words (60)
    digest: str                             # SHA-256 over sorted (relpath, bytes) of every YAML file read

@dataclass(frozen=True)
class PlanSection:
    section: Section
    facts: tuple[Fact, ...]

@dataclass(frozen=True)
class Plan:
    structure: Structure
    sections: tuple[PlanSection, ...]
    unused_facts: tuple[Fact, ...]
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class AdaptedPlan:
    structure: Structure
    source: Persona
    target: Persona
    sections: tuple[PlanSection, ...]
    substitutions: dict[str, str]   # active glossary map (preferred + optional plain)
    cta_style: str | None           # None unless >=1 kept fact has kind == FactKind.ASK
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class RewriteRule:
    id: str
    description: str
    added_tokens: frozenset[str]    # lowercase apostrophe-preserving tokens this rule may add
    apply: Callable[[str], list[str]]

@dataclass(frozen=True)
class Sentence:
    text: str
    fact_ids: tuple[str, ...] = ()
    frame: bool = False             # True: closing line; fact_ids MUST be empty

@dataclass(frozen=True)
class DraftSection:
    name: str
    heading: str
    sentences: tuple[Sentence, ...]

@dataclass(frozen=True)
class Draft:
    sections: tuple[DraftSection, ...]
    title: str | None = None
    warnings: tuple[str, ...] = ()
    candidates_considered: int = 1
    backend: BackendKind = BackendKind.RULES
    declared_additions: frozenset[str] = frozenset()  # lowercase tokens added by registered rules / glossary
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Constraints:
    max_words: int | None = None
    max_chars: int | None = None
    banned: tuple[str, ...] = ()
    candidates: int = 8
    seed: int = 0
    min_voice: float | None = None

@dataclass(frozen=True)
class CheckFinding:
    code: str
    level: CheckLevel
    message: str
    section: str | None = None
    sentence_index: int | None = None

@dataclass(frozen=True)
class FeatureScore:
    name: str
    dimension: str
    author_value: float
    candidate_value: float
    sigma: float
    z: float
    score: float
    pinned: bool = False

@dataclass(frozen=True)
class GapItem:
    feature: str
    dimension: str
    score: float
    author_value: float
    candidate_value: float
    sigma: float
    explanation: str

@dataclass(frozen=True)
class ConformanceReport:
    overall: float                  # 0.0..100.0
    band: MatchBand
    confidence: ConfidenceBand
    word_count: int
    dimensions: dict[str, float]    # dimension -> 0.0..1.0
    features: tuple[FeatureScore, ...]
    largest_gaps: tuple[GapItem, ...]        # up to 6 items scoring < 0.5, worst first
    signature_matches: tuple[str, ...]       # reported, not scored
    frame_matches: tuple[str, ...]           # reported, not scored

@dataclass(frozen=True)
class Validation:
    ok: bool                        # True iff zero findings have level == CheckLevel.ERROR
    findings: tuple[CheckFinding, ...]
    persona_score: float            # 0.0..100.0 (share of 4 persona check categories passed * 100)
    voice_report: ConformanceReport | None
    fidelity_mode: FidelityMode

@dataclass(frozen=True)
class FactTraceEntry:
    section: str
    text: str
    frame: bool
    facts: tuple[dict[str, str], ...]   # [{"id": ..., "kind": ..., "source": ..., "text": ...}]

@dataclass(frozen=True)
class BackendRecord:
    requested: BackendKind
    used: BackendKind
    deterministic: bool
    model: str | None = None
    prompt_sha256: str | None = None
    response_sha256: str | None = None

@dataclass(frozen=True)
class ReproducibilityRecord:
    tool_version: str
    seed: int
    candidates: int
    selectors: dict[str, str | None]    # structure, modality, source, target, author
    input_hashes: dict[str, str]
    facts_digest: str
    config_digest: str
    author_corpus_sha256: str | None
    output_sha256: str
    backend: BackendRecord
    record_sha256: str                  # first 16 hex chars of SHA-256 of canonical JSON excluding record_sha256

@dataclass(frozen=True)
class Brief:
    structure: str
    modality: str
    source: str
    target: str
    author: str | None = None
    inputs: tuple[str, ...] = ()
    notes: str | None = None
    topic: str | None = None
    seed: int = 0
    candidates: int = 8
    min_voice: float | None = None
    banned: tuple[str, ...] = ()
    fact_overrides: dict[str, FactKind] = field(default_factory=dict)
    project_dir: str | None = None
    authors_dir: str = "authors"
    backend: BackendKind | str = BackendKind.RULES   # validated into BackendKind in pipeline.generate()
    fallback: bool = True
    timeout: int = 90
    model: str | None = None

@dataclass(frozen=True)
class Result:
    text: str
    draft: Draft
    validation: Validation
    fact_trace: tuple[FactTraceEntry, ...]
    record: ReproducibilityRecord
    facts: tuple[Fact, ...]

@dataclass(frozen=True)
class DriftIssue:
    kind: str                       # "orphan_edit" | "unscored_pin" | "drifted_pin"
    path: str
    message: str

@dataclass(frozen=True)
class DriftReport:
    author_id: str
    issues: tuple[DriftIssue, ...]

@dataclass(frozen=True)
class AuthorSummary:
    id: str
    display_name: str
    source_count: int
    total_words: int
    has_curated: bool
    has_local: bool
    schema_version: int

@dataclass(frozen=True)
class AuthorDiff:
    author_a: str
    author_b: str
    feature_deltas: tuple[dict[str, Any], ...]  # [{"feature", "dimension", "value_a", "value_b", "delta", "normalized_delta"}], sorted by |normalized_delta| desc

@dataclass(frozen=True)
class BackendAvailability:
    backend: BackendKind
    available: bool
    executable: str | None
    version: str | None
    reason: str | None

@dataclass(frozen=True)
class BackendStatusReport:
    backends: dict[str, BackendAvailability]
```

## 3. Typed Error Hierarchy (`src/casper/errors.py`)

`pipeline.generate` and `commands.write_draft` **never** raise on draft validation errors — they always return `Result` with `result.validation.ok == False`, and `cli.py` exits with code `1`.

```python
class CasperError(Exception):
    code: str = "casper-error"
    exit_code: int = 2
    http_status: int = 400
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None: ...

class InputError(CasperError):              # Missing notes, unreadable file, bad YAML/flag/backend, unscorable text
    code = "input-error"; exit_code = 2; http_status = 400

class LibraryError(CasperError):            # Invalid persona/structure/modality combo or schema violation
    code = "library-error"; exit_code = 2; http_status = 400

class ProfileError(CasperError):            # Corrupt profile YAML or invalid layer directive
    code = "profile-error"; exit_code = 2; http_status = 400

class ProfileNotFoundError(ProfileError):   # Valid author ID does not exist in authors_dir
    code = "profile-not-found"; exit_code = 2; http_status = 404

class ProfileTamperedError(ProfileError):   # body_sha256 mismatch on save_profile without --force
    code = "profile-tampered"; exit_code = 3; http_status = 409

class BackendError(CasperError):            # CLI writer unavailable, auth error, timeout, empty output
    code = "backend-error"; exit_code = 2; http_status = 502

class SecurityError(CasperError):           # Non-loopback bind, bad Host/Origin/Sec-Fetch-Site, path traversal, SSRF, zip bomb
    code = "security-error"; exit_code = 2; http_status = 403

class PayloadTooLargeError(CasperError):    # HTTP body > 256 KiB or notes > 40,000 / text > 60,000 chars
    code = "payload-too-large"; exit_code = 2; http_status = 413

class BusyError(CasperError):               # Single-flight lock acquisition timed out under slow CLI load
    code = "server-busy"; exit_code = 2; http_status = 503
```

## 4. Author Profile YAML Schema & Layer Merge Algebra

### 4.1 Generated Layer (`authors/<id>.yaml`) — Complete Schema

```yaml
schema_version: 1
author:
  id: "bill"
  display_name: "Bill"
  aliases: ["William"]
  # NEVER contains email or consent (ADR 0005)
generated:
  tool: "casper"
  tool_version: "0.1.0"
  date: "2026-11-20T00:00:00Z"
  spacy_model: "en_core_web_sm"
  corpus_sha256: "<sha256 of sorted source sha256s>"
  body_sha256: "<sha256 of canonical JSON of profile excluding generated.body_sha256>"
corpus:
  document_count: 4
  total_words: 5200
  avg_doc_words: 1300.0
style_guide:
  # Exactly 8 deterministic rules, 1 per area (id == area):
  # sentences | paragraphs | lexical | voice | punctuation | rhetoric | headings | structure
  - { id: "sentences",   area: "sentences",   rule: "..." }
  - { id: "paragraphs",  area: "paragraphs",  rule: "..." }
  - { id: "lexical",     area: "lexical",     rule: "..." }
  - { id: "voice",       area: "voice",       rule: "..." }
  - { id: "punctuation", area: "punctuation", rule: "..." }
  - { id: "rhetoric",    area: "rhetoric",    rule: "..." }
  - { id: "headings",    area: "headings",    rule: "..." }
  - { id: "structure",   area: "structure",   rule: "..." }
sentences:
  count: 318
  length_words: { mean: 16.4, median: 15.0, p10: 7.0, p90: 27.0, stdev: 7.2 }
  short_rate_le8: 0.16
  long_rate_ge30: 0.07
  burstiness_cv: 0.44
  passive_rate: 0.08
  subordinate_clauses_per_sentence: 0.62
  commas_per_sentence: 1.05
  fragment_rate: 0.03
  question_rate: 0.04
  exclamation_rate: 0.005
  starts:
    conjunction_rate: 0.06
    pronoun_rate: 0.14
    adverb_or_transition_rate: 0.11
    top_first_words: [["The", 42], ["We", 21], ["This", 18]]
paragraphs:
  count: 112
  sentences_per_paragraph: { mean: 2.84, median: 3.0 }
  words_per_paragraph: { mean: 46.4, median: 44.0 }
  single_sentence_rate: 0.21
  long_paragraph_rate_ge120w: 0.04
lexical:
  words: 5200
  flesch_kincaid_grade: 10.4
  flesch_reading_ease: 54.2
  mean_word_length: 4.95
  long_word_rate_ge7: 0.28
  acronyms_per_1k: 12.1
voice:
  person_per_1k:
    first_singular: 2.5
    first_plural_inclusive: 11.4
    second: 9.8
    third_plural: 6.2
  contractions_per_1k: 8.4
  negations_per_1k: 7.1
  punctuation_per_1k:
    em_dash: 4.2
    colon: 5.1
    semicolon: 1.2
    parenthetical: 3.5
    quotes: 6.8
  commas_per_1k: 58.2
  oxford_comma_rate: 0.88
  lexicon_per_1k:
    transitions: 11.2
    intensifiers: 4.0
    hedges: 3.1
  rhetoric:
    contrast_frames_per_1k: 1.8       # e.g. "not X; it is Y" / "not X, but Y"
    acronym_introductions: 6          # e.g. "Long Name (LN)"
typography:
  quote_style: "straight"             # straight | curly | mixed | none
  links_per_1k: 4.6
headings:
  count: 24
  density_per_1k: 4.62                # headings per 1,000 prose words
  mean_words: 4.8
  case_style: "sentence"              # sentence | title | upper | mixed | none
  case_shares: { sentence: 0.75, title: 0.25, upper: 0.0 }
lists:
  item_count: 32
  items_per_1k: 6.15
  emphasis_lead_rate: 0.34
structure:
  mean_doc_words: 1300.0
  mean_sections: 6.0
  has_summary_rate: 0.50
  closing_patterns: ["question", "action", "summary"]
function_word_per_1k:
  # All 60 function words from lexicons.yaml mapped to rate per 1,000 prose words
  the: 54.2
signature:
  recurring_phrases: ["in practice", "at the edge"]     # top <=12 recurring 2-4 grams (>=2 docs)
  bounded_phrases: ["when you need to"]                 # top <=12 function-word-bounded n-grams
  sentence_frames: ["The result is ..."]                # top <=8 recurring opener frames
exemplars:
  openers: ["Start with the constraint that matters most."]   # up to 4
  closers: ["Measure the change before expanding scope."]     # up to 4
  short_lines: ["Nothing is invented."]                       # up to 4 (<=8 words)
stability:
  mean_sentence_length: { min: 14.2, max: 18.9, stdev: 1.8 }
  # ... all 32 STABILITY_KEYS
sources:
  - title: "..."
    source: "..."
    byline: "..."
    byline_matches_author: true
    prose_words: 1320
    sha256: "..."
```

**Canonical `body_sha256` algorithm:** Deep-copy the profile dict, delete `copy["generated"]["body_sha256"]` if present, serialize with `json.dumps(copy, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`, and hash UTF-8 bytes with SHA-256.

**Tamper check & atomic save (`save_profile`):**
1. `check_profile_writable(path, force=False)` runs **before** corpus analysis in `author build`.
2. If `path` exists and `existing["generated"].get("body_sha256")` is present and `!= compute_body_sha256(existing)`:
   - If `force=False`: raise `ProfileTamperedError` (CLI exit 3).
   - If `force=True`: copy existing file to `<path>.bak` before replacing.
3. Legacy files lacking `generated.body_sha256` are overwritten without `--force`.
4. Write to `<path>.tmp.<pid>` in the same directory, flush + `os.fsync`, then `os.replace` onto `<path>`; clean up temp file on any exception.

### 4.2 Layer Merge Algebra (`layers.resolve`)

Precedence order (lowest → highest):
1. `generated` (`<id>.yaml`)
2. `curated` (`<id>.curated.yaml`, tracked in git)
3. `local` (`<id>.local.yaml`, gitignored, created via `os.open(..., O_WRONLY|O_CREAT|O_EXCL, 0o600)`)
4. For each `overlay_name` in `overlays`: `curated.overlays[overlay_name]`, then `local.overlays[overlay_name]`. The `overlays` container key itself is **stripped** from the returned `merged_profile`.

Merge rules:
- **Mappings:** merge recursively key by key.
- **Scalars:** later layer replaces earlier value.
- **Lists (general):** plain list assignment in a higher layer raises `ProfileError`; lists mutate only via `{"$add": [...], "$remove": [...], "$replace": [...]}` (`$replace` replaces whole list; otherwise `$remove` filters then `$add` appends non-duplicates). Provenance records the list path (`"author.aliases"`) as the winning layer.
- **`style_guide` edits:** keyed by rule `id` (`{rule_id: value}` in `curated`/`local`):
  - `str` → replaces `rule` text on existing entry with matching `id` (missing `id` → `orphan_edit`).
  - `"$remove"` → deletes entry with matching `id` (missing `id` → `orphan_edit`).
  - `{"area": str, "rule": str}` → updates existing `id` or appends `{id, area, rule}`.
  - Anything else → `orphan_edit`.
  - Provenance records `"style_guide.<rule_id>"` → winning layer.
- **Pins:** `pins: {<feature_name>: {"value": float, "stdev": float?}}` overrides author target value (and optionally `stdev`) during `conformance.score`. `drift_report` reports:
  - `orphan_edit`, `unscored_pin` (not in `STABILITY_KEYS`), and `drifted_pin` (`|pin.value - generated_value| > max(generated_stdev, 0.1 * |generated_value|)`).

## 5. Voice Conformance Scoring Math (ADR 0006)

1. Extract features via `features.analyze([document], nlp)`. If `words < 1` or `sentences.count < 1`, raise `InputError("Candidate text has no scorable prose")`.
2. `widen = min(1.5, max(1.0, sqrt(avg_doc_words / max(candidate_words, 1))))`.
3. For each of the 32 features in `STABILITY_KEYS`:
   - `author_val = pin.value` if pinned else profile path value.
   - `raw_stdev = pin.stdev` if pinned with stdev else `profile["stability"][key]["stdev"]`.
   - `sigma = max(raw_stdev, floor, 0.1 * abs(author_val)) * widen`.
   - `z = abs(candidate_val - author_val) / sigma`.
   - `feature_score = exp(-(z ** 2) / 4.5)`.
4. **Dimension scores:**
   - 7 scalar dimensions (`rhythm`, `openers`, `paragraphs`, `register`, `point_of_view`, `punctuation`, `rhetoric`): weighted arithmetic mean of member feature scores.
   - **`function_words`:** cosine similarity `cos` over the 60 fixed function words from `lexicons.yaml`; `score = clip((cos - 0.85) / (0.97 - 0.85), 0.0, 1.0)`.
   - **`structure`:** included **only** if candidate `headings.count >= 2` AND profile `headings.count > 0`:
     - `density_sigma = max(1.5, 0.25 * profile.headings.density_per_1k) * widen`
     - `density_score = exp(-((abs(cand.headings.density_per_1k - prof.headings.density_per_1k) / density_sigma) ** 2) / 4.5)`
     - `case_score = 1.0 - 0.5 * sum(abs(cand.headings.case_shares[k] - prof.headings.case_shares[k]) for k in ("sentence", "title", "upper"))` (L1 complement in `[0.0, 1.0]`)
     - `structure_score = 0.5 * (density_score + case_score)`
5. **Overall score:** `100.0 * exp(sum(w_d * ln(max(score_d, 0.02)) for d in active_dims) / sum(w_d for d in active_dims))`.
   - Dimension weights: `rhythm=1.5`, `openers=0.7`, `paragraphs=0.8`, `register=1.2`, `point_of_view=1.2`, `punctuation=1.0`, `rhetoric=0.9`, `function_words=1.2`, `structure=0.8`.
6. **Bands:** `>=80` `strong`, `>=65` `close`, `>=45` `partial`, `<45` `different`. **Confidence:** `>=1000` `high`, `>=250` `medium`, `<250` `low`.
7. **Largest gaps:** Up to 6 features with `feature_score < 0.5`, sorted by `(feature_score, feature_name)`.

### The 32 Scored Features (`STABILITY_KEYS`)

| # | Feature Key | Dimension | Weight | Floor | Profile Path |
|---|---|---|---:|---:|---|
| 1 | `mean_sentence_length` | `rhythm` | 2.0 | 2.0 | `sentences.length_words.mean` |
| 2 | `short_sentence_rate` | `rhythm` | 1.0 | 0.04 | `sentences.short_rate_le8` |
| 3 | `long_sentence_rate` | `rhythm` | 1.0 | 0.04 | `sentences.long_rate_ge30` |
| 4 | `sentence_length_cv` | `rhythm` | 0.7 | 0.08 | `sentences.burstiness_cv` |
| 5 | `passive_rate` | `rhythm` | 1.0 | 0.08 | `sentences.passive_rate` |
| 6 | `commas_per_sentence` | `rhythm` | 0.7 | 0.25 | `sentences.commas_per_sentence` |
| 7 | `subordinate_clauses_per_sentence` | `rhythm` | 0.7 | 0.20 | `sentences.subordinate_clauses_per_sentence` |
| 8 | `fragment_rate` | `rhythm` | 0.7 | 0.03 | `sentences.fragment_rate` |
| 9 | `question_rate` | `rhythm` | 0.7 | 0.02 | `sentences.question_rate` |
| 10 | `exclamation_rate` | `rhythm` | 0.7 | 0.01 | `sentences.exclamation_rate` |
| 11 | `conjunction_start_rate` | `openers` | 0.7 | 0.03 | `sentences.starts.conjunction_rate` |
| 12 | `pronoun_start_rate` | `openers` | 0.8 | 0.06 | `sentences.starts.pronoun_rate` |
| 13 | `transition_start_rate` | `openers` | 0.8 | 0.05 | `sentences.starts.adverb_or_transition_rate` |
| 14 | `sentences_per_paragraph` | `paragraphs` | 1.5 | 0.60 | `paragraphs.sentences_per_paragraph.mean` |
| 15 | `single_sentence_paragraph_rate` | `paragraphs` | 1.0 | 0.10 | `paragraphs.single_sentence_rate` |
| 16 | `flesch_kincaid_grade` | `register` | 2.0 | 1.20 | `lexical.flesch_kincaid_grade` |
| 17 | `mean_word_length` | `register` | 1.0 | 0.15 | `lexical.mean_word_length` |
| 18 | `long_word_rate` | `register` | 0.7 | 0.04 | `lexical.long_word_rate_ge7` |
| 19 | `acronyms_per_1k` | `register` | 0.8 | 5.00 | `lexical.acronyms_per_1k` |
| 20 | `first_person_singular_per_1k` | `point_of_view` | 1.2 | 1.50 | `voice.person_per_1k.first_singular` |
| 21 | `first_person_plural_per_1k` | `point_of_view` | 1.2 | 2.50 | `voice.person_per_1k.first_plural_inclusive` |
| 22 | `second_person_per_1k` | `point_of_view` | 1.2 | 2.50 | `voice.person_per_1k.second` |
| 23 | `contractions_per_1k` | `point_of_view` | 1.2 | 2.50 | `voice.contractions_per_1k` |
| 24 | `em_dashes_per_1k` | `punctuation` | 1.0 | 1.50 | `voice.punctuation_per_1k.em_dash` |
| 25 | `colons_per_1k` | `punctuation` | 1.0 | 3.00 | `voice.punctuation_per_1k.colon` |
| 26 | `semicolons_per_1k` | `punctuation` | 0.7 | 1.50 | `voice.punctuation_per_1k.semicolon` |
| 27 | `parentheses_per_1k` | `punctuation` | 0.7 | 2.00 | `voice.punctuation_per_1k.parenthetical` |
| 28 | `commas_per_1k` | `punctuation` | 0.7 | 8.00 | `voice.commas_per_1k` |
| 29 | `transitions_per_1k` | `rhetoric` | 0.8 | 3.00 | `voice.lexicon_per_1k.transitions` |
| 30 | `intensifiers_per_1k` | `rhetoric` | 0.8 | 3.00 | `voice.lexicon_per_1k.intensifiers` |
| 31 | `hedges_per_1k` | `rhetoric` | 0.8 | 3.00 | `voice.lexicon_per_1k.hedges` |
| 32 | `contrast_frames_per_1k` | `rhetoric` | 0.8 | 1.00 | `voice.rhetoric.contrast_frames_per_1k` |

## 6. Complete Shipped YAML Libraries Specification (ADR 0008)

### 6.1 Personas (10 total: 5 `source`, 5 `target`)

| Kind | ID | Depth | Jargon | Priorities | `vocabulary_include` | `vocabulary_avoid` | `typical_concerns` | `framing_patterns` | `cta_styles` | `section_priority` |
|---|---|---|---|---|---|---|---|---|---|---|
| `source` | `developer` | `high` | `high` | `reliability, latency, testing, deployment` | `build, deploy, benchmark, patch` | `synergy` | `regression, blocker, debt` | `evidence_first` | `technical_review, direct` | `progress, risks, next_steps` |
| `source` | `tech_lead` | `high` | `medium` | `architecture, trade-offs, risk, delivery` | `milestone, interface, design, migration` | `synergy` | `coupling, outage, scope` | `tradeoff_summary` | `decision, alignment, direct` | `status, risks, decisions, next_steps` |
| `source` | `product_owner` | `medium` | `low` | `outcomes, timeline, customer, adoption` | `release, customer, value, milestone` | `refactor, boilerplate` | `delay, churn, scope` | `outcome_first` | `approval, alignment, feedback` | `status, decisions, next_steps, risks` |
| `source` | `project_manager` | `medium` | `low` | `schedule, dependencies, blockers, ownership` | `schedule, owner, target, blocker` | `refactor` | `slip, dependency, staffing` | `status_first` | `approval, direct, alignment` | `status, risks, next_steps, asks` |
| `source` | `analyst` | `high` | `medium` | `metrics, baseline, trend, variance` | `baseline, cohort, rate, delta` | `anecdotal` | `sample, bias, anomaly` | `metric_first` | `feedback, decision` | `evidence, recommendation, risks` |
| `target` | `management` | `low` | `low` | `schedule, risk, budget, impact` | `timeline, impact, owner, risk` | `mutex, syscall, refactor` | `delay, escalation, cost` | `bottom_line_up_front` | `approval, direct` | `status, risks, asks, next_steps` |
| `target` | `executive` | `low` | `low` | `strategy, revenue, decision, risk` | `outcome, impact, decision, milestone` | `mutex, schema, refactor, endpoint` | `revenue, compliance, slip` | `executive_brief` | `approval, decision` | `status, recommendation, risks, asks` |
| `target` | `engineering` | `high` | `high` | `design, performance, correctness, rollout` | `latency, interface, rollout, test` | `synergy, leverage` | `regression, bottleneck, edge` | `technical_detail` | `technical_review, direct` | `context, details, risks, next_steps` |
| `target` | `product_owner` | `medium` | `low` | `scope, release, customer, feedback` | `release, feature, customer, readiness` | `syscall, mutex` | `scope, readiness, blocker` | `release_readiness` | `alignment, approval, feedback` | `status, progress, risks, asks` |
| `target` | `customer` | `low` | `low` | `benefit, reliability, usability, schedule` | `update, improvement, reliability, support` | `internal, ticket, sprint, refactor` | `downtime, breaking, migration` | `benefit_first` | `feedback, next_step` | `summary, progress, next_steps` |

### 6.2 Structures (3 total; 11 valid `structure × modality` pairs)

1. **`status_update`** — Goal: *Communicate current state, progress, blockers, and immediate actions.* Compatible modalities: `slack`, `email`, `memo`, `plain`. Default targets: `management`, `product_owner`.
   - `status` (heading `"Status"`, purpose `"Current health and headline metrics"`, required `true`, `fact_kinds: [status, metric]`, `min_words: 5, max_words: 80`)
   - `progress` (heading `"Progress"`, purpose `"Completed work since last update"`, required `false`, `fact_kinds: [progress]`, `min_words: 0, max_words: 120`)
   - `risks` (heading `"Risks & Blockers"`, purpose `"Active blockers or risks"`, required `false`, `fact_kinds: [risk]`, `min_words: 0, max_words: 100`)
   - `next_steps` (heading `"Next Steps"`, purpose `"Immediate planned actions"`, required `false`, `fact_kinds: [next_step]`, `min_words: 0, max_words: 100`)
   - `asks` (heading `"Asks"`, purpose `"Decisions or approvals needed"`, required `false`, `fact_kinds: [ask]`, `min_words: 0, max_words: 80`)
2. **`decision_memo`** — Goal: *Present context, recommendation, evidence, risks, and approval ask.* Compatible modalities: `memo`, `email`, `article`, `plain`. Default targets: `executive`, `management`, `engineering`.
   - `context` (heading `"Context"`, purpose `"Background and current state"`, required `true`, `fact_kinds: [background, status]`, `min_words: 10, max_words: 200`)
   - `recommendation` (heading `"Recommendation"`, purpose `"Proposed decision"`, required `true`, `fact_kinds: [decision]`, `min_words: 5, max_words: 180`)
   - `evidence` (heading `"Evidence"`, purpose `"Metrics and supporting details"`, required `false`, `fact_kinds: [metric, detail, progress]`, `min_words: 0, max_words: 250`)
   - `risks` (heading `"Risks"`, purpose `"Trade-offs and mitigations"`, required `false`, `fact_kinds: [risk]`, `min_words: 0, max_words: 180`)
   - `asks` (heading `"Next Steps & Asks"`, purpose `"Requested sign-off and follow-up"`, required `false`, `fact_kinds: [ask, next_step]`, `min_words: 0, max_words: 120`)
3. **`technical_article`** — Goal: *Explain a technical topic with context, findings, decisions, and takeaways.* Compatible modalities: `article`, `memo`, `plain`. Default targets: `engineering`, `customer`.
   - `summary` (heading `"Overview"`, purpose `"Context and headline state"`, required `true`, `fact_kinds: [background, status]`, `min_words: 10, max_words: 300`)
   - `details` (heading `"Technical Details"`, purpose `"Architecture, progress, and measurements"`, required `true`, `fact_kinds: [detail, progress, metric]`, `min_words: 15, max_words: 1200`)
   - `decisions` (heading `"Key Decisions"`, purpose `"Design choices and rationale"`, required `false`, `fact_kinds: [decision]`, `min_words: 0, max_words: 400`)
   - `risks` (heading `"Limitations & Risks"`, purpose `"Known constraints and risks"`, required `false`, `fact_kinds: [risk]`, `min_words: 0, max_words: 350`)
   - `next_steps` (heading `"What Comes Next"`, purpose `"Planned work and reader calls to action"`, required `false`, `fact_kinds: [next_step, ask]`, `min_words: 0, max_words: 250`)

### 6.3 Modalities (5 total)

| ID | Markup | `max_words` | `max_chars` | `title` | `headings` | `bullets` | Description |
|---|---|---:|---:|:---:|---|:---:|---|
| `slack` | `slack` | `180` | `1200` | `false` | `slack_bold` | `true` | Short Slack channel update |
| `email` | `markdown` | `350` | `2500` | `true` | `bold` | `true` | Concise email update |
| `memo` | `markdown` | `800` | `6000` | `true` | `h2` | `true` | Structured internal Markdown memo |
| `article` | `html` | `2500` | `20000` | `true` | `h2` | `false` | Long-form HTML technical article |
| `plain` | `plain` | `200` | `1400` | `false` | `none` | `false` | Unformatted plain-text summary |

### 6.4 Glossary, Phrasebank, Lexicons & Validator Stop-Word List

- **`glossaries/default.yaml`:**
  - `plain`: `{latency: "response time", throughput: "capacity", idempotent: "safe to repeat", regression: "unexpected breakage", deprecation: "planned removal", telemetry: "usage metrics", concurrency: "parallel work", endpoint: "service address", schema: "data format", rollback: "undo change"}`
  - `preferred`: `{utilize: "use", leverage: "use", "in order to": "to", "prior to": "before", "at this point in time": "now", "due to the fact that": "because"}`
  - `banned`: `["synergy", "disruptive", "bleeding-edge", "game-changer", "rockstar"]`
- **`phrasebank.yaml`:**
  - `approval`: `["Please let me know if you approve.", "Please confirm if we are approved to proceed."]`
  - `alignment`: `["Please share any concerns so we can stay aligned.", "Let me know if this matches your expectations."]`
  - `decision`: `["Please confirm which option you want to take.", "Let me know your decision when ready."]`
  - `direct`: `["Please reply with your answer.", "Let me know how you want to proceed."]`
  - `feedback`: `["Please share your feedback when convenient.", "Let me know what you think."]`
  - `next_step`: `["Please reach out if you have any questions.", "Let us know if you need help with the next step."]`
  - `technical_review`: `["Please review the details and flag any technical issues.", "Let me know if you spot any gaps."]`
- **`lexicons.yaml`:**
  - `transitions`: `["however", "therefore", "moreover", "furthermore", "meanwhile", "consequently", "additionally", "instead", "otherwise", "nonetheless", "nevertheless", "similarly", "finally", "next", "also", "still", "then", "thus", "yet"]`
  - `intensifiers`: `["very", "really", "extremely", "highly", "strongly", "deeply", "completely", "totally", "absolutely", "significantly", "substantially", "critically"]`
  - `hedges`: `["perhaps", "maybe", "possibly", "probably", "likely", "seem", "seems", "seemed", "appear", "appears", "somewhat", "roughly", "around", "nearly", "might", "could", "tend", "tends"]`
  - `negations`: `["no", "not", "never", "none", "nobody", "nothing", "neither", "nowhere", "cannot", "can't", "won't", "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't", "hadn't", "wouldn't", "couldn't", "shouldn't", "without"]`
  - `function_words` (exact 60 words): `["the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on", "with", "he", "as", "you", "do", "at", "this", "but", "his", "by", "from", "they", "we", "say", "her", "she", "or", "an", "will", "my", "one", "all", "would", "there", "their", "what", "so", "up", "out", "if", "about", "who", "get", "which", "go", "me", "when", "make", "can", "like", "time", "no", "just", "him", "know", "take"]`
- **Validator closed stop-word list (`STRICT` mode, words `len > 3` always permitted in syntactic glue):**
  `{"that", "this", "these", "those", "with", "from", "into", "onto", "over", "under", "about", "after", "before", "between", "through", "during", "while", "where", "when", "which", "whose", "whom", "their", "there", "they", "them", "have", "been", "being", "were", "will", "would", "could", "should", "shall", "must", "does", "done", "each", "both", "more", "most", "some", "such", "than", "then", "also", "only", "very", "just", "your", "ours", "status", "owner", "risk", "blocker", "next", "step", "decision", "progress", "background", "metric", "request"}`

---

<!-- source: spec/02-contracts.md -->

# 02 — Stage Contracts, Uniform Surfaces & Security Boundaries

All interfaces below are binding contracts. Implementation tasks must satisfy these exact signatures, invariants, error types, and surface parity requirements.

## 1. Stage-by-Stage Python Contracts

### 1.1 Document Loaders (`src/casper/loaders/`)

```python
def load_document(
    path_or_url: str | Path,
    *,
    max_bytes: int = 10_485_760,      # 10 MiB hard cap
    timeout: float = 30.0,            # URL fetch timeout in seconds
    max_redirects: int = 5,
    url_opener: Callable[..., Any] | None = None,  # injectable seam for tests
) -> Document: ...

def load_bytes(
    data: bytes,
    name: str,
    *,
    content_type: str | None = None,
) -> Document: ...

def collect_input_paths(inputs: Sequence[str | Path]) -> list[str]: ...
```

**Contract rules:**
- **Content-first dispatch:** Detect format by magic bytes first, then `content_type`, then extension:
  - `%PDF-` → `pdf` (`pypdf`)
  - `{\rtf` → `rtf` (`striprtf`, one paragraph per non-empty line)
  - `\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1` → `doc` (system converter `antiword`/`soffice` if on `PATH`, else raise `InputError`)
  - `PK\x03\x04` → inspect zip entries: enforce uncompressed total size `<= min(5 * max_bytes, 52_428_800)` (50 MiB, else `SecurityError`); `word/document.xml` → `docx` (`python-docx`); `content.xml` + `mimetype` containing `opendocument.text` → `odt`
  - HTML content-type or `.html`/`.htm` → `html` (BeautifulSoup + lxml; extract JSON-LD & `<meta>` for title/authors/published/modified/canonical_url/description; strip `<script>/<style>/<nav>/<footer>`; tag blocks inside `<aside>` or sections whose heading matches `^(summary|tl;?dr|abstract|key takeaways)$` as `BlockKind.SUMMARY`, `^(audience|who this is for|prerequisites)$` as `BlockKind.AUDIENCE`, and `^(resources|references|further reading|related links)$` as `BlockKind.RESOURCES`)
  - `.tex` → `latex` (custom extractor stripping preamble/comments/macros, preserving sections/paragraphs/lists/quotes)
  - `.csv` → `csv` (`loaders/tabular.py`: each row formatted as `"<Col>: <Val>"` blocks preserving headers)
  - `.yaml`/`.yml` → `yaml` (`loaders/tabular.py`: top-level mappings/lists flattened into `"<Key>: <Val>"` blocks)
  - `.md`/`.markdown`/`.txt`/other UTF-8 text → `markdown`/`text`: parses YAML front matter, ATX headings, lists, blockquotes, fenced code, and strips inline markup. **Line-break preservation for `Key: value`:** any line matching `^(status|state|owner|risks?|blocker|next|next steps?|ask|request|decision|progress|done|background|context|metric)\s*:\s*.+$` (case-insensitive) is emitted as its own dedicated `Block(kind=BlockKind.PARAGRAPH)` BEFORE adjacent prose lines are joined into paragraphs.
- **URL fetching & SSRF protection (GC-06):**
  - Allow `http://` and `https://` schemes **only** (all others raise `SecurityError`).
  - Resolve target hostname via `socket.getaddrinfo` before connecting; reject any IP where `ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified` with `SecurityError`.
  - Disable automatic redirect following; manually handle up to `max_redirects` (5), re-validating both scheme and resolved IP on **every** redirect hop.
  - Stream response enforcing `max_bytes` (10 MiB) and `timeout` (30s).
- **Directory traversal:** `collect_input_paths` expands directories in deterministic sorted order and skips any directory matching `*_files` or hidden dot-directories.
- **Voice exclusion:** Blocks with `kind in EXCLUDED_VOICE_BLOCK_KINDS` are excluded from prose word counts and voice feature extraction.

### 1.2 NLP Parsing & Shared Rewrite Rules (`src/casper/parsing.py`, `src/casper/rewrites.py`)

```python
# parsing.py
def load_nlp(*, ner: bool = False) -> spacy.language.Language: ...

# rewrites.py (Rank 1 — imported downward by BOTH realizer.py and validator.py)
REWRITE_RULES: tuple[RewriteRule, ...]
ALLOWED_RULE_TOKENS: frozenset[str]   # union of rule.added_tokens across REWRITE_RULES
```

Built-in `REWRITE_RULES`:
1. `plain`: identity (`added_tokens=frozenset()`).
2. `contract`: standard contractions (`do not`→`don't`, `does not`→`doesn't`, `did not`→`didn't`, `it is`→`it's`, `we are`→`we're`, `they are`→`they're`, `is not`→`isn't`, `are not`→`aren't`, `cannot`→`can't`, `will not`→`won't`, `have not`→`haven't`, `has not`→`hasn't`) declaring exact lowercase contraction tokens.
3. `expand`: reverses contractions back to full forms declaring exact lowercase expanded tokens.
4. `transition_opener`: prepends one opener from `("Also,", "Next,", "Additionally,", "Finally,")` for non-initial facts in a section (`added_tokens=frozenset({"also", "next", "additionally", "finally"})`).
5. `semicolon_merge`: merges first two short (`<=12` words each) consecutive sentences with `"; "` when the second does not start with a transition (`added_tokens=frozenset()`). Only lowercases the first character of sentence 2 if its first token is NOT a proper noun/acronym (i.e., not all-caps and not in the cited facts' `entities`/`owners` and not `"I"`).

### 1.3 Feature Extraction & Author Profile (`src/casper/features/`, `src/casper/profile.py`)

```python
STABILITY_KEYS: tuple[str, ...]  # exact 32 keys listed in 01-data-model.md §5

def analyze(docs: Sequence[Document], nlp: Language | None = None) -> dict[str, Any]: ...

def build_profile(
    author_id: str,
    display_name: str,
    inputs: Sequence[str | Path],
    *,
    aliases: Sequence[str] = (),
    strict_authors: bool = False,
    min_words: int = 150,
    nlp: Language | None = None,
) -> dict[str, Any]: ...

def render_style_guide(features: dict[str, Any]) -> list[dict[str, str]]: ...
def compute_body_sha256(profile: dict[str, Any]) -> str: ...
def check_profile_writable(path: Path, *, force: bool = False) -> None: ...
def save_profile(path: Path, profile: dict[str, Any], *, force: bool = False) -> Path: ...
def load_profile(path: Path) -> dict[str, Any]: ...
```

- `render_style_guide` deterministically emits exactly 8 rules (1 per area, `id == area`: `sentences`, `paragraphs`, `lexical`, `voice`, `punctuation`, `rhetoric`, `headings`, `structure`) formatted strictly from numeric feature values.
- `build_profile` drops documents with `< min_words` prose words; with `strict_authors=True`, also drops docs whose byline does not match `display_name`/`aliases`. Raises `InputError` if 0 documents remain.

### 1.4 Profile Layers (`src/casper/layers.py`)

```python
def resolve(
    generated: dict[str, Any],
    curated: dict[str, Any] | None = None,
    local: dict[str, Any] | None = None,
    *,
    overlays: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, str]]: ...

def load_resolved_profile(
    profile_path: Path,
    *,
    overlays: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, str]]: ...

def drift_report(
    generated: dict[str, Any],
    curated: dict[str, Any] | None = None,
    local: dict[str, Any] | None = None,
) -> DriftReport: ...

def write_local_email(authors_dir: Path, author_id: str, email: str) -> Path: ...
```

- `write_local_email` writes atomically using `os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)` → `fsync` → `os.replace`, ensuring private data is **never** world/group-readable even transiently.

### 1.5 Voice Conformance & Catalog (`src/casper/conformance.py`, `src/casper/catalog.py`)

```python
def score(
    profile: dict[str, Any],
    document: Document,
    *,
    nlp: Language | None = None,
) -> ConformanceReport: ...

def list_authors(authors_dir: Path) -> list[AuthorSummary]: ...

def find_profile(
    author_ref: str,
    authors_dir: Path,
    *,
    allow_path: bool = True,
) -> Path: ...

def diff_authors(profile_a: dict[str, Any], profile_b: dict[str, Any]) -> AuthorDiff: ...
```

- `find_profile`: when `allow_path=False` (Web API), `author_ref` must match `^[a-z0-9][a-z0-9_-]{0,63}$` and resolve strictly inside `authors_dir.resolve()` (else `SecurityError` → HTTP `403`); if valid ID is missing, raises `ProfileNotFoundError` (HTTP `404`).
- `diff_authors`: for each of the 32 `STABILITY_KEYS`, computes `delta = value_b - value_a`, `scale = max(floor, 0.5 * (stdev_a + stdev_b), 0.1 * max(abs(value_a), abs(value_b)))`, and `normalized_delta = delta / scale`; returns entries sorted descending by `abs(normalized_delta)`.

### 1.6 Libraries (`src/casper/libraries.py`)

```python
def load_libraries(project_dir: Path | None = None) -> Libraries: ...
def check_combo(
    libs: Libraries,
    structure_id: str,
    modality_id: str,
    target_id: str,
    source_id: str | None = None,
) -> None: ...
```

### 1.7 Fact Ingestion (`src/casper/facts.py`)

```python
def ingest(
    inputs: Sequence[str | Path] = (),
    notes: str | None = None,
    *,
    nlp: Language | None = None,
    fact_overrides: Mapping[str, FactKind] | None = None,
) -> FactModel: ...
```

**Deterministic pipeline inside `ingest`:**
1. Validate non-empty input (else `InputError("Nothing to write from")`). Load every path via `loaders.load_document` (including `.csv`, `.yaml`, `.yml`) and inline `notes` via `loaders.load_bytes(..., "<inline>")`.
2. Extract candidate statements preserving `Key: value` blocks, then deduplicate on normalized text (`re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")`) BEFORE assigning sequential IDs `f001`, `f002`, ... (`^f\d{3,}$`).
3. Classify each fact by precedence:
   1. Inline tag prefix `^\[(status|progress|risk|next_step|decision|background|detail|metric|ask)\]\s*` (stripped from text).
   2. Explicit `"Key: value"` block (`status|state`→`status`, `owner`→`detail`+owner, `risk|risks|blocker`→`risk`, `next|next step|next steps`→`next_step`, `ask|request`→`ask`, `decision`→`decision`, `progress|done`→`progress`, `background|context`→`background`, `metric`→`metric`), restated using only source words (e.g. `"The status is on track."`).
   3. Nearest enclosing heading matched against `_HEADING_KIND`:
      - `status`: `r"\b(status|state|health|summary|overview)\b"`
      - `progress`: `r"\b(progress|done|completed|shipped|highlights)\b"`
      - `risk`: `r"\b(risks?|blockers?|issues?|concerns?|limitations?)\b"`
      - `next_step`: `r"\b(next\s+steps?|upcoming|plan|actions?|todo)\b"`
      - `decision`: `r"\b(decisions?|recommendation|options?|trade-?offs?)\b"`
      - `metric`: `r"\b(metrics?|numbers?|kpis?|measurements?|benchmarks?)\b"`
      - `ask`: `r"\b(asks?|requests?|approvals?|sign-?off|help\s+needed)\b"`
      - `background`: `r"\b(background|context|history|motivation)\b"`
   4. Tightened keyword cues (`_CUES`) in priority order:
      - `ask`: `r"\b(please|could you|can you|would you|need your|approve|approval|sign\s+off|action\s+required|let me know)\b"` (`"review"` alone is **excluded**).
      - `risk`: `r"\b(blocked|blocker|risk|at risk|delayed|slipping|outage|incident|regression|mitigat)\b"`
      - `decision`: `r"\b(decided|decision|recommend|chose|chosen|selected|approved)\b"`
      - `progress`: `r"\b(completed|finished|shipped|deployed|merged|landed|migrated|implemented)\b"`
      - `next_step`: `r"\b(next|will\s+\w+|plan\s+to|scheduled|upcoming|targeting)\b"`
      - `status`: `r"\b(on track|off track|green|yellow|red|healthy|degraded|in progress)\b"`
      - `metric`: `r"(?:[+-]?\d+(?:[.,]\d+)*\s*(?:%|ms|s|sec|kb|mb|gb|tb|rps|qps|x)|[$€£]\s*\d)"`
   5. Default: `background` for paragraph 0 when no heading applies, else `detail`.
4. Apply `fact_overrides`: if any key in `fact_overrides` does not match an extracted `Fact.id`, raise `InputError(f"Unknown fact id in fact_overrides: {fid}")`.
5. Raise `InputError("No facts could be extracted")` if 0 facts survive.

### 1.8 Plan & Adapt (`src/casper/planner.py`)

```python
def plan_structure(model: FactModel, structure: Structure) -> Plan: ...
def adapt(plan: Plan, source: Persona, target: Persona, glossary: Glossary) -> AdaptedPlan: ...
```

- Exact behavior as specified: `(-salience, order)` single-use assignment; depth cap `1/3/6` with `+0.3` source keyword (`len>=4`) boost; ascending `fact.order` output; `target.section_priority` ordering; `preferred` + optional `plain` (`jargon_level == LOW`); `cta_style` set **only** when `≥1` kept fact has `kind == FactKind.ASK`.

### 1.9 Modality Formatting & Counting (`src/casper/modalities.py`)

```python
def format_draft(draft: Draft, modality: Modality) -> str: ...
def count_rendered(draft: Draft, modality: Modality) -> tuple[int, int]: ...  # (word_count, char_count)
```

- `format_draft` never modifies sentence wording (`plain`, `html` with `html.escape`, `markdown`, `slack`).
- `count_rendered`: renders `text = format_draft(draft, modality)`. `char_count = len(text)`. For `word_count`, if `modality.markup == MarkupKind.HTML`, strip HTML tags (`re.sub(r"<[^>]+>", " ", text)`) and unescape entities before splitting on whitespace; for `plain`/`markdown`/`slack`, strip markdown heading/bullet punctuation (`#`, `*`, `-`) and count whitespace-separated tokens.

### 1.10 Realizer (`src/casper/realizer.py`)

```python
def substitute(text: str, mapping: Mapping[str, str]) -> str: ...

def fit_to_limits(
    draft: Draft,
    adapted_plan: AdaptedPlan,
    constraints: Constraints,
    modality: Modality,
) -> Draft: ...

class RuleBasedRealizer:
    def __init__(self, libs: Libraries, *, rules: Sequence[RewriteRule] = REWRITE_RULES) -> None: ...
    def realize(
        self,
        adapted_plan: AdaptedPlan,
        voice: dict[str, Any] | None,
        constraints: Constraints,
        modality: Modality,
        *,
        nlp: Language | None = None,
    ) -> Draft: ...
```

- **OOM-safe sampling:** Compute `total = math.prod(len(v) for v in variants_per_fact)`. If `total <= 512`, enumerate all indices; if `total > 512`, deterministically sample `511` distinct flat indices from `range(1, total)` via `random.Random(seed)` plus index `0` (all-plain variant) and decode flat index → tuple via modular arithmetic without ever materializing `itertools.product`.
- **Performance guard:** Deduplicate identical rendered candidate texts before scoring; when `voice is None`, pick candidate 0 without invoking spaCy; share a text-keyed parse cache across candidate evaluations within one `realize()` call.
- `fit_to_limits` evaluates `count_rendered(draft, modality)` against `constraints.max_words` / `constraints.max_chars`, dropping lowest-salience cited facts (protecting the first fact of each `required` section) and dropping the closing frame if no `ASK` fact remains.

### 1.11 CLI Agent Writers (`src/casper/llm.py`, ADR 0010)

```python
CommandRunner = Callable[[Sequence[str], Path, float, Mapping[str, str]], tuple[int, str, str]]

class CliAgentRealizer:
    def __init__(
        self,
        backend: BackendKind,            # BackendKind.CLAUDE | BackendKind.AGY
        libs: Libraries,
        *,
        timeout: int = 90,
        model: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None: ...

    def build_prompt(
        self,
        adapted_plan: AdaptedPlan,
        voice: dict[str, Any] | None,
        constraints: Constraints,
    ) -> str: ...

    def realize(
        self,
        adapted_plan: AdaptedPlan,
        voice: dict[str, Any] | None,
        constraints: Constraints,
        modality: Modality,
        *,
        nlp: Language | None = None,
    ) -> Draft: ...

def status(*, timeout: float = 20.0, runner: CommandRunner | None = None) -> BackendStatusReport: ...
```

- Prompt allowlist excludes `author`, `sources`, `email`, `consent`, and any path whose provenance starts with `"local"`.
- Citation regex: `r"\[(f\d{3,}(?:\s*,\s*f\d{3,})*)\]\s*$"` (supports `f001`..`f1000+`).
- Exact subprocess commands (`shell=False`, fresh empty temp `cwd`, `stdin=DEVNULL`, minimal env allowlist):
  - `claude`: `[exe, "-p", "--output-format", "text", *(("--model", model) if model else ()), prompt]` (`CASPER_CLAUDE_CLI`, `CASPER_CLAUDE_MODEL`).
  - `agy`: `[exe, "-p", "--output-format", "text", *(("--model", model) if model else ()), prompt]` (`CASPER_AGY_CLI`, `CASPER_AGY_MODEL`).

### 1.12 Validator (`src/casper/validator.py`)

```python
def validate(
    draft: Draft,
    adapted_plan: AdaptedPlan,
    fact_model: FactModel,
    voice: dict[str, Any] | None,
    constraints: Constraints,
    modality: Modality,
    *,
    fidelity_mode: FidelityMode,
    glossary: Glossary,
    nlp: Language | None = None,
) -> Validation: ...
```

- **Tokenization:** Apostrophe-preserving regex `r"[a-zA-Z]+(?:'[a-zA-Z]+)*"` so `"doesn't"` stays a single token.
- **Numeric extraction:** Signed numeric regex `r"[+-]?\d+(?:[.,]\d+)*%?"` (so `"+12%"` vs `"-12%"` fails `unsupported-number`).
- **Title validation:** If `draft.title` is non-empty, check `draft.title` against `banned-term` and `glossary`.
- **Per-fact polarity check (`ASSISTED`):** Exclude benign idioms (`not only`, `no later than`, `no issues`, `zero issues`). Flag `polarity-mismatch` (`ERROR`) if:
  1. Single-fact citation `[f001]` has different negation parity than `f001`, OR
  2. Multi-fact citation `[f001, f002, ...]` has sentence negation presence (`has_neg(sentence)`) that disagrees with ALL cited facts when all cited facts agree in polarity (e.g., all cited facts affirmative yet sentence introduces negation, or all cited facts negated yet sentence is purely affirmative), OR
  3. Sentence introduces an antonym flip word from `{(approved, rejected), (on track, blocked), (passed, failed), (increased, decreased), (slipped, ahead), (enabled, disabled), (delayed, accelerated), (added, removed)}` whose opposite appears in the cited facts while the introduced word does not.
- **Name check (`ASSISTED`, including index 0):** Flag `unsupported-name` (`ERROR`) for any capitalized token `[A-Z][a-zA-Z0-9_-]+` at index `> 0` not in cited facts/replacements, **AND** for any token at index `0` that is a proper noun (`PROPN` or camel/internal-cap token like `ZorgCorp`) whose lowercase form does not appear in cited facts, `Draft.declared_additions`, or the closed stop-word list.
- **Check codes (all 22):** `frame-with-facts`, `untraced`, `unknown-fact`, `unsupported-number`, `unsupported-claim` (`STRICT` error) / `reworded` (`ASSISTED` warning), `unsupported-name` (`ASSISTED` error), `polarity-mismatch` (`ASSISTED` error), `undeclared-addition` (`STRICT` error), `empty`, `too-long`, `too-long-chars` (evaluated via `count_rendered(draft, modality)`), `banned-term`, `glossary`, `persona-avoid`, `persona-jargon`, `persona-depth`, `persona-order`, `voice-low-confidence`, `voice-unscorable`, `voice-below-threshold`, `plan`.

### 1.13 Pipeline (`src/casper/pipeline.py`)

```python
def generate(
    brief: Brief,
    *,
    libs: Libraries | None = None,
    nlp: Language | None = None,
    runner: CommandRunner | None = None,
    allow_author_path: bool = True,
) -> Result: ...
```

- Coerces/validates `brief.backend` into `BackendKind` upfront (invalid string → `InputError`).
- Resolves author profile via `find_profile(..., allow_path=allow_author_path)` and `load_resolved_profile(..., overlays=(brief.modality,))`.
- Never raises on validation errors; always returns `Result`.

## 2. Uniform Surfaces Architecture (`src/casper/commands.py`)

`commands.py` (Rank 7) owns exactly **10** typed domain operations. Python API (`src/casper/__init__.py`), CLI (`cli.py`), and HTTP API (`web/server.py`) all route through these exact 10 functions.

```python
# Exact signatures in src/casper/commands.py
def write_draft(brief: Brief, *, allow_author_path: bool = True, runner: CommandRunner | None = None) -> Result: ...
def extract_facts(inputs: Sequence[str | Path] = (), notes: str | None = None, *, fact_overrides: Mapping[str, FactKind] | None = None) -> FactModel: ...
def score_draft(author_ref: str, text_or_path: str | Path, *, authors_dir: Path = Path("authors"), is_text: bool = False, raw: bool = False, overlay: str | None = None, allow_author_path: bool = True) -> ConformanceReport: ...
def list_options(*, project_dir: Path | None = None, authors_dir: Path = Path("authors")) -> dict[str, Any]: ...
def backend_status(*, timeout: float = 20.0, runner: CommandRunner | None = None) -> BackendStatusReport: ...
def author_build(author_id: str, display_name: str, inputs: Sequence[str | Path], *, authors_dir: Path = Path("authors"), aliases: Sequence[str] = (), email: str | None = None, min_words: int = 150, strict_authors: bool = False, force: bool = False) -> dict[str, Any]: ...
def author_inspect(author_ref: str, *, authors_dir: Path = Path("authors")) -> dict[str, Any]: ...
def author_show(author_ref: str, *, authors_dir: Path = Path("authors"), resolved: bool = False, overlay: str | None = None) -> dict[str, Any]: ...
def author_list(*, authors_dir: Path = Path("authors")) -> list[AuthorSummary]: ...
def author_diff(author_a: str, author_b: str, *, authors_dir: Path = Path("authors")) -> AuthorDiff: ...
```

`src/casper/__init__.py` lazily exports all 10 commands (`write_draft` + alias `generate`, `extract_facts`, `score_draft`, `list_options`, `backend_status`, `author_build`, `author_inspect`, `author_show`, `author_list`, `author_diff`), core types (`Brief`, `Result`, `Fact`, `FactKind`, `BackendKind`, `Validation`, `ConformanceReport`), and errors (`CasperError` subclasses).

### 2.1 Surface Parity Matrix

| # | Core Command (`commands.py`) | Python API (`casper.*`) | CLI (`casper`) | Web HTTP API | Web UI (`web/static/`) |
|---:|---|---|---|---|---|
| 1 | `write_draft` | `casper.write_draft` / `generate` | `casper write` | `POST /api/generate` | **Write** tab → Generate (chips, 3 views: Draft/Provenance/Checks, Copy, Download) |
| 2 | `extract_facts` | `casper.extract_facts` | `casper write --dry-run [--json]` | `POST /api/extract` | **Write** tab → Inspect Facts (with kind overrides) |
| 3 | `score_draft` | `casper.score_draft` | `casper author score [--raw] [--json]` | `POST /api/score` | **Check a draft** tab → Score |
| 4 | `list_options` | `casper.list_options` | `casper write --list-options [--json]` | `GET /api/options` | Selectors + incompatible format disabling |
| 5 | `backend_status` | `casper.backend_status` | `casper write --backend-status [--json]` | `GET /api/backend-status` | Backend readiness badges |
| 6 | `author_build` | `casper.author_build` | `casper author build` | *Excluded (E-01)* | *Excluded (E-01)* |
| 7 | `author_inspect` | `casper.author_inspect` | `casper author inspect [--json]` | *Excluded (E-01)* | *Excluded (E-01)* |
| 8 | `author_show` | `casper.author_show` | `casper author show [--resolved] [--json]` | *Excluded (E-01)* | *Excluded (E-01)* |
| 9 | `author_list` | `casper.author_list` | `casper author list [--json]` | `GET /api/options` (`authors`) | Author selector |
| 10 | `author_diff` | `casper.author_diff` | `casper author diff <a> <b> [--json]` | *Excluded (E-02)* | *Excluded (E-02)* |

*Outside `commands.py`:* `casper serve` (`cli.py` → `web.server.make_server`) and `scripts/start.sh` / `stop.sh` bootstrap the HTTP server (*Excluded from HTTP/UI per E-03*). `POST /api/token` returns `501` (*E-04*).

## 3. CLI Contract (`src/casper/cli.py`)

- **Streams:** `casper write` prints **only** formatted draft to `stdout`; scores, warnings, errors, and fallback notices go to `stderr`. Informational commands (`--dry-run`, `--backend-status`, `--list-options`, `author inspect|show|list|diff|score`) support `--json` for deterministic machine-readable output used by `TC-017` parity tests.
- **Exit codes:** `0` ok; `1` `Validation.ok == False`; `2` `InputError`/`LibraryError`/`ProfileError`/`ProfileNotFoundError`/`BackendError`(`--no-fallback`)/`SecurityError`; `3` `ProfileTamperedError`.
- **`casper write` flags:** `--structure`, `--modality`, `--source`, `--target`, `--author`, `-i/--input` (repeatable), `--notes`, `--topic`, `--seed`, `--candidates`, `--min-voice`, `--banned` (repeatable), `--fact-override FID=KIND` (repeatable), `--project-dir`, `--authors-dir`, `--backend rules|claude|agy`, `--no-fallback`, `--timeout` (default 90), `--model`, `--out` (also writes `<out>.trace.json`), `--brief <yaml>` (YAML keys match `Brief` fields; `fact_overrides` coerced `str -> FactKind`; explicit CLI flags override brief file), `--dry-run`, `--backend-status`, `--list-options`, `--json`.
- **`casper author` flags:** shared `--authors-dir <dir>` (default `authors`), plus:
  - `build --id ID --name NAME [--alias A]... [--email E] [--min-words 150] [--strict-authors] [--force] INPUT...`
  - `inspect <id> [--json]` (prints summary + drift report)
  - `show <id> [--resolved] [--overlay MOD] [--json]`
  - `score <id> <file> [--raw] [--overlay MOD] [--json]` (`--raw` loads raw `<id>.yaml` ignoring curated, local, and `--overlay`; if both `--raw` and `--overlay` are passed, raises `InputError`)
  - `list [--json]`
  - `diff <id_a> <id_b> [--json]`
- **`casper serve` flags:** `--host` (default `127.0.0.1`; non-loopback rejected with exit 2), `--port` (default `8731`), `--authors-dir` (default `authors`), `--project-dir`.

## 4. Web HTTP API & Security Contract (`src/casper/web/server.py`)

- **Pure core:** `App.handle(method: str, path: str, headers: Mapping[str, str], body: bytes) -> HttpResponse(status, headers, body)`.
- **Pre-read Handler guards:** `Handler` sets socket timeout (`15s` for request read), rejects chunked `Transfer-Encoding` (`411`), parses `Content-Length` as non-negative int before reading, and rejects `Content-Length > 262_144` with `413` BEFORE reading `rfile`.
- **Request gates (in order):**
  1. `Host` header required (HTTP/1.0 missing `Host` → `403`); must exact-match `127.0.0.1:<port>` or `localhost:<port>` (case-insensitive, zero whitespace/userinfo) → else `403`.
  2. If `Origin` present: must exact-match `http://127.0.0.1:<port>` or `http://localhost:<port>` → else `403`.
  3. If `Sec-Fetch-Site` present: must be in `{"same-origin", "none"}` → else `403`.
  4. Method check: `OPTIONS` and unsupported methods → `405` (with `Allow` header).
  5. On `POST`: `Content-Type` media type must be `application/json` → else `415`; `len(body) <= 262_144` → else `413`; valid JSON object with zero unknown keys → else `400`.
- **Static path sanitizer (`/static/<relpath>`):** strip query string, reject NUL bytes, backslashes, or `..` segments after URL-unquoting, verify `target.resolve().is_relative_to(static_root.resolve())` and `target.is_file()` → else `404`.
- **Concurrency:** Single-flight `threading.Lock` wraps `POST /api/generate`, `POST /api/extract`, and `POST /api/score` with `lock.acquire(timeout=30.0)` — if busy past timeout, returns `503 {"error": "Server busy; try again shortly"}`.
- **Mandatory headers on EVERY response:** `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`.
- **Error JSON shape:** `{"error": str, "code": str}` (500 always returns `{"error": "Internal server error", "code": "internal-error"}`).

### Exact HTTP Endpoint Schemas

| Endpoint | Request JSON (exact allowed keys) | Response JSON (`200` unless noted) |
|---|---|---|
| `GET /` | — | `text/html; charset=utf-8` |
| `GET /static/<rel>` | — | Static asset (`css`/`js`/`svg`/`png`/`ico`) |
| `GET /api/options` | — | `{"personas": {"source": [...], "target": [...]}, "structures": [...], "modalities": [...], "authors": [...], "backends": ["rules","claude","agy"]}` |
| `GET /api/backend-status` | — | `{"backends": {"rules": {...}, "claude": {...}, "agy": {...}}}` |
| `POST /api/extract` | `{"notes": str (req, <=40000), "fact_overrides": dict[str,str] (opt)}` | `{"facts": [Fact.to_dict()], "warnings": [str]}` |
| `POST /api/generate` | `{"structure": str (req), "modality": str (req), "source": str (req), "target": str (req), "notes": str (req, <=40000), "author": str\|null (opt, catalog ID only), "topic": str\|null (opt), "seed": int (opt, 0), "candidates": int (opt, 8), "min_voice": float\|null (opt), "banned": [str] (opt), "fact_overrides": dict[str,str] (opt), "backend": str (opt, "rules"), "fallback": bool (opt, true), "timeout": int (opt, 120), "model": str\|null (opt)}` | `{"text": str, "validation": Validation.to_dict(), "fact_trace": [FactTraceEntry.to_dict()], "record": ReproducibilityRecord.to_dict(), "facts": [Fact.to_dict()], "backend": BackendRecord.to_dict()}` |
| `POST /api/score` | `{"author": str (req, catalog ID only), "text": str (req, <=60000), "raw": bool (opt, false), "overlay": str\|null (opt)}` | `{"report": ConformanceReport.to_dict()}` |
| `POST /api/token` | any valid JSON | `501 {"error": "API tokens are not supported; Casper runs locally.", "code": "not-implemented"}` |

### Static UI Contract (`src/casper/web/static/`)
- Single-page app (`index.html`, `app.js`, `theme.css`, `img/*`), zero frameworks, zero build step, zero external CDNs.
- All server strings written strictly via `textContent` (zero `innerHTML`/`outerHTML`/`document.write`).
- Tabs: **Write**, **Check a draft**, **About**.
- **Write** tab: disables modalities incompatible with selected structure; backend readiness badges from `/api/backend-status`; disabled API token field; **Inspect Facts** button (`POST /api/extract`) with per-fact kind override dropdowns; **Generate** button (`POST /api/generate`); result summary chips (voice score/band, persona score, validation status, backend used); **three result views** (Draft, Where each sentence came from, Checks); **Copy** and **Download** buttons.

## 5. Operational & Verification Gate Contracts

### `scripts/start.sh` & `scripts/stop.sh`
- PID file: `target/casper.pid` (gitignored); background log: `target/casper-server.log`; default port: `8731`.
- `start.sh [--background] [--open] [--port N] [--no-install]`: creates `.venv` with `uv` if absent, installs editable package when imports fail (unless `--no-install`), refuses if port is already bound or live PID in `target/casper.pid` is a Casper process, warns on stderr when `authors/` has no `.yaml` files.
- `stop.sh`: reads `target/casper.pid`, verifies `/proc/<pid>/cmdline` (NUL-delimited) or `ps -p <pid> -o args=` contains `casper` and `serve` before sending `SIGTERM` (refuses with exit 1 if PID belongs to another process), removes stale PID file.

### `scripts/verify.sh`
```text
Usage: scripts/verify.sh [--quick | --tier <t1,t2> | --only <stage...> | --match <expr> | --failed | --list | --status | --report]
Stdout (exactly one line):
  PASS <passed>/<total> <secs>s skips=<k>
  FAIL <failed>/<total>: <stage1>,<stage2> -> target/verify/<stage1>/fail.txt
Exit code: 0 on PASS, 1 on FAIL
```
- Sets `CASPER_IN_VERIFY=1` in child processes so `test_verify_gate.py` never recurses infinitely.
- Artifacts in gitignored `target/verify/`: `STATUS`, `summary.tsv`, `report.md`, `junit.xml`, and per-stage `status`, `fail.txt` (`<=40` lines), `log`.
- `--quick`: `lint-ruff`, `type-mypy`, `spec-sync`, `secret-scan`, `smoke`, `unit`.
- `--tier smoke,unit,integration,system,security`: pre-milestone gate.
- Full run (no flags): all 8 tiers + coverage gate (`>=90%` line, `>=85%` branch on `src/casper/`).

---

<!-- source: spec/03-test-matrix.md -->

# 03 — Pre-Build Exhaustive Test Matrix & Threat Model

Every test case below is specified **before implementation**, instantiated as a failing test first (RED), satisfied minimally (GREEN), and wired permanently into `tests/<tier>/` for automatic discovery by `scripts/verify.sh`.

## 1. Pre-Build Exhaustive Test Matrix

### Dimension 1: Happy Path & Contract Invariants

| ID | Scenario & Input | Expected Outcome | Tier | Target Test File |
|---|---|---|---|---|
| **TC-001** | `casper --help`, `casper write --help`, `casper author --help`, `casper serve --help` | Exit 0; all subcommands and documented flags present | `smoke` | `tests/smoke/test_cli_boot.py` |
| **TC-002** | `scripts/build_spec.py --check` against `SPEC.md` | Exit 0; generated `SPEC.md` byte-identical to `spec/0[0-9]-*.md` | `smoke` | `tests/smoke/test_spec.py` |
| **TC-003** | ADR register `docs/adr/README.md` vs. `docs/adr/[0-9]*.md` | 1-to-1 parity; every accepted ADR has non-empty "Enforced by" | `smoke` | `tests/smoke/test_adr.py` |
| **TC-004** | Hygiene: `.gitignore` rules, doc relative links, zero forbidden third-party brand strings; brand static sync (`src/casper/web/static/img/*` vs `docs/brand/*` once brand assets exist in Task 14) | Zero broken links, zero brand leakage, byte-identical synced assets | `smoke` | `tests/smoke/test_hygiene.py` |
| **TC-005** | AST import graph across `src/casper/` against strict Rank 1..8 DAG (`00-overview.md §3`) | Zero upward/cyclic imports; `commands` never imports `cli`/`web`; `validator` never imports `realizer`/`llm` | `smoke` | `tests/smoke/test_architecture.py` |
| **TC-006** | `load_document` & `load_bytes` for HTML (JSON-LD + meta + SUMMARY/AUDIENCE/RESOURCES tagging), Markdown (front matter + `Key: value` block preservation), LaTeX, DOCX, PDF, RTF, CSV, YAML | Valid `Document` with exact `format`, `sha256`, `title`, `blocks`; excluded voice blocks tagged properly | `unit` | `tests/unit/test_loaders.py` |
| **TC-007** | `build_profile` on 4 synthetic sample documents (`>=150` words each) | Valid YAML with `schema_version=1`, all 11 feature groups, 32 `STABILITY_KEYS`, 60 function words, 8 `style_guide` areas, `body_sha256`, zero `email` | `unit` | `tests/unit/test_profile.py` |
| **TC-008** | `layers.resolve` across `generated`, `curated`, `local`, and `overlays=("slack",)` | Exact precedence, list `$add`/`$remove`/`$replace`, `style_guide` id-keyed edits, `overlays` stripped from output, complete `provenance` map | `unit` | `tests/unit/test_layers.py` |
| **TC-009** | `conformance.score` on matching vs. contrasting prose + pinned feature + `structure` dimension (`>=2` headings) | Deterministic score `0..100`, exact band/confidence, exact `structure` density/case score, `<=6` `largest_gaps` `<0.5`, pins override target | `unit` | `tests/unit/test_conformance.py` |
| **TC-010** | `load_libraries` shipped data + `project_dir` override + `check_combo` | Loads 10 personas (incl. `(source, product_owner)` & `(target, product_owner)`), 3 structures, 5 modalities, 1 glossary, 60 function words, stable `digest` | `unit` | `tests/unit/test_libraries.py` |
| **TC-011** | `facts.ingest` with `Key: value`, inline `[risk]`/`[ask]` tags, headings, tightened cues, CSV/YAML inputs, and `fact_overrides` | Exact `FactKind`, salience values, deduplication before ID assignment, NetworkX `DiGraph` `mentions` + `follows` edges | `unit` | `tests/unit/test_facts.py` |
| **TC-012** | `planner.plan_structure` + `planner.adapt` for low/medium/high depth and low/high jargon | Depth caps `1/3/6`, source-keyword `+0.3` boost, ascending source order, `section_priority` reorder, CTA only when `ASK` kept | `unit` | `tests/unit/test_planner.py` |
| **TC-013** | `RuleBasedRealizer.realize` + `substitute` + `fit_to_limits` | Whole-word case-preserving longest-first substitution; `semicolon_merge` preserves proper nouns; `Draft.declared_additions` matches applied `REWRITE_RULES`; limits enforced on `count_rendered(draft, modality)` | `unit` | `tests/unit/test_realizer.py` |
| **TC-014** | `format_draft` & `count_rendered` across `plain`, `html`, `markdown`, `slack` | Wording 100% unchanged; valid HTML5 escaping; bullets only for `>=2` non-frame sentences; closing frame never bulleted; HTML tags excluded from word count | `unit` | `tests/unit/test_modalities.py` |
| **TC-015** | `catalog.list_authors`, `find_profile`, `diff_authors` | Sorted `AuthorSummary`, ID resolution, normalized delta ordering | `unit` | `tests/unit/test_catalog.py` |
| **TC-016** | End-to-end `pipeline.generate` for all 11 valid `structure × modality` pairs using synthetic `tests/fixtures/` vs. `tests/golden/` | Exact golden output match; `Validation.ok == True`; complete `fact_trace` and `record.record_sha256` | `integration` | `tests/integration/test_golden.py` |
| **TC-017** | Surface parity table test: `write_draft`, `extract_facts`, `score_draft`, `list_options`, `backend_status` across Python API (`commands.py`), CLI (`--json`), and Web HTTP `App.handle` | Byte-identical draft text, identical `record_sha256`, identical `facts`, and identical `Validation.ok` across all three surfaces | `system` | `tests/system/test_surface_parity.py` |
| **TC-018** | CLI `casper write --out <file>` + `--brief <yaml>` + `--fact-override` + `casper author build|inspect|show|score|list|diff --authors-dir <tmp>` | Exit 0; stdout clean draft, stderr scores/warnings; `<file>.trace.json` matches schema | `system` | `tests/system/test_cli_e2e.py` |
| **TC-019** | Real localhost TCP socket round trip (`make_server` on ephemeral port) for `/`, `/static/app.js`, `/api/options`, `/api/backend-status`, `/api/extract`, `/api/generate`, `/api/score`, `/api/token` | HTTP 200 (501 for `/api/token`), all security headers present, valid JSON | `system` | `tests/system/test_web_e2e.py` |

### Dimension 2: Boundary & Equivalence Partitions

| ID | Scenario & Input | Expected Outcome | Tier | Target Test File |
|---|---|---|---|---|
| **TC-020** | `"The team will review the plan."` vs. `"Please review and approve the plan."` | First is **not** `ask` (zero closing CTA); second is `ask` (emits closing CTA) | `unit` | `tests/unit/test_facts.py` |
| **TC-021** | `build_profile` document prose word counts: `0`, `149`, `150`, `151` (`min_words=150`) | `0` and `149` dropped; `150` and `151` retained; all-dropped raises `InputError` | `unit` | `tests/unit/test_profile.py` |
| **TC-022** | `conformance.score` word counts: `0`, `1`, `249` (`LOW`), `250` (`MEDIUM`), `999` (`MEDIUM`), `1000` (`HIGH`); headings: `0`, `1` (no `structure`), `2` (`structure` active) | `0` raises `InputError`; exact confidence & dimension transitions | `unit` | `tests/unit/test_conformance.py` |
| **TC-023** | `fit_to_limits` and validator at `max_words - 1`, `max_words`, `max_words + 1` and `max_chars - 1`, `max_chars`, `max_chars + 1` (including HTML tags) | Exact inclusive boundary pass; `+1` trimmed or triggers `too-long` / `too-long-chars` | `unit` | `tests/unit/test_validator.py` |
| **TC-024** | Unicode, smart quotes, em dashes, accents, emoji, contractions (`"doesn't"`), `*_files` asset folders | Clean UTF-8 handling, apostrophe-preserving tokenization, `*_files` skipped | `unit` | `tests/unit/test_loaders.py` |
| **TC-025** | Web payload boundaries: body `262_144` (pass) vs. `262_145` (413); notes `40_000` (pass) vs. `40_001` (413); score text `60_000` (pass) vs. `60_001` (413) | Exact boundary enforcement without partial processing | `unit` | `tests/unit/test_web_app.py` |
| **TC-026** | Realizer variant explosion: section with 15 facts (`3^15 = 14,348,907` combinations) | Direct index sampling capped at 512 (zero OOM), always includes all-plain variant, completes `<0.5s` | `stress` | `tests/stress/test_realizer_bounds.py` |
| **TC-027** | Hypothesis property tests (`100+` generated inputs) on `substitute`, `format_draft`, and `layers.resolve` | `format_draft` preserves every sentence token; `substitute` is case-preserving; `layers.resolve` provenance covers every leaf | `integration` | `tests/integration/test_properties.py` |

### Dimension 3: Negative, Malformed & Adversarial Inputs

| ID | Scenario & Input | Expected Outcome | Tier | Target Test File |
|---|---|---|---|---|
| **TC-028** | Forbidden dependency scan (`transformers`, `torch`, `openai`, `anthropic`, `huggingface_hub`, `litellm`, etc.) in `pyproject.toml` and `src/` | Passes cleanly; negative fixture proves detector catches forbidden import | `security` | `tests/security/test_constraints.py` |
| **TC-029** | Validator fidelity attacks (`STRICT` & `ASSISTED`): invented number (`$999`), flipped sign (`+12%`→`-12%`), invented mid-sentence AND sentence-initial proper name (`ZorgCorp`), single-fact & multi-fact polarity flip (`approved`→`rejected`, `not`), benign idiom non-regression (`not only`, `no issues`), uncited sentence, frame with `fact_ids`, unknown `f999`, undeclared rule addition, banned word in body OR `Draft.title`, leftover preferred term | Every attack triggers exact `CheckFinding.code` (`ERROR`, `Validation.ok == False`); benign idioms do NOT false-positive | `security` | `tests/security/test_fidelity.py` |
| **TC-030** | Privacy leak attacks: `write_local_email` + CLI `author build --email secret@example.com` + `llm.build_prompt` inspection + tracked-file scan | Email written **only** to `.local.yaml` with mode `0600` (never transiently `0644`); zero email/local/author-block bytes in `<id>.yaml` or CLI prompt | `security` | `tests/security/test_privacy.py` |
| **TC-031** | Hand-edited `<id>.yaml` (tampered without updating `body_sha256`) on `save_profile` / `casper author build` | Raises `ProfileTamperedError` / CLI exit `3` **before** corpus analysis; `--force` writes `.bak` and succeeds | `unit` | `tests/unit/test_layers.py` |
| **TC-032** | Web security attacks: `make_server("0.0.0.0", ...)`, missing/bad `Host` (incl. `localhost:8731@evil.com`), foreign `Origin`, `Sec-Fetch-Site: cross-site` and `same-site`, `OPTIONS` method (`405`), non-JSON `Content-Type` (`415`), unknown JSON field (`400`), author path traversal `../etc/passwd` (`403`), missing valid author ID (`404`), static traversal `/static/..%2f..%2fpyproject.toml` / NUL / backslash (`404`) | Exact status codes (`403`/`404`/`405`/`415`/`400`); `SecurityError` on non-loopback bind; zero leaks | `security` | `tests/security/test_web_security.py` |
| **TC-033** | XSS payload `<script>alert(1)</script>` in notes formatted to `html` + static UI JS scan | Escaped as `&lt;script&gt;` in HTML output; `web/static/app.js` contains zero `innerHTML`/`outerHTML`/`document.write` | `security` | `tests/security/test_web_security.py` |
| **TC-034** | SSRF & URL scheme attacks: `file:///etc/passwd`, `ftp://host/x`, `http://127.0.0.1:8731/`, `http://169.254.169.254/latest/meta-data/`, and public URL redirecting `302` → `http://127.0.0.1/` | Every case raises `SecurityError` immediately without opening connection to private/forbidden target | `security` | `tests/security/test_loaders_security.py` |
| **TC-035** | Invalid combos & negatives: invalid `structure×modality`, unknown persona/structure/modality, unknown `--backend foobar`, empty notes, unknown `fact_overrides` ID, `--raw` combined with `--overlay`, plain list overwrite in layer without `$add/$remove/$replace` | Exact typed `LibraryError` / `InputError` / `ProfileError` listing valid choices; CLI exit `2` | `unit` | `tests/unit/test_errors.py` |
| **TC-036** | Drift report on curated layer with orphaned `style_guide` edit, unscored pin, and drifted pin (`> max(stdev, 0.1*|val|)`) | `DriftReport` returns exact `orphan_edit`, `unscored_pin`, `drifted_pin` entries | `unit` | `tests/unit/test_layers.py` |

### Dimension 4: Idempotency, State & Concurrency

| ID | Scenario & Input | Expected Outcome | Tier | Target Test File |
|---|---|---|---|---|
| **TC-037** | Repeated `pipeline.generate` calls with identical `Brief` and `seed` across fresh processes | Byte-identical `text`, `fact_trace`, and `record_sha256`; changing `seed` alters variant ranking deterministically when candidates differ | `integration` | `tests/integration/test_determinism.py` |
| **TC-038** | Atomic `save_profile` + repeated `write_local_email` calls | Zero lingering `.tmp.*` files; `.local.yaml` created `0600` atomically; idempotent on repeat | `unit` | `tests/unit/test_profile.py` |
| **TC-039** | 8 concurrent `POST /api/generate` threads against `ThreadingHTTPServer` + busy-lock `503` timeout test | Single-flight lock serializes runs cleanly (all 8 return 200 with identical deterministic output); lock contention beyond timeout returns `503` | `stress` | `tests/stress/test_web_concurrency.py` |
| **TC-040** | `scripts/start.sh` on busy port and double-start; `scripts/stop.sh` with `target/casper.pid` pointing to non-Casper process (`sleep`) | `start.sh` refuses busy port/running instance; `stop.sh` refuses to kill non-Casper PID | `system` | `tests/system/test_scripts.py` |

### Dimension 5: Dependency Failure & Degradation

| ID | Scenario & Input | Expected Outcome | Tier | Target Test File |
|---|---|---|---|---|
| **TC-041** | Fake CLI (`tests/fakes/fake_agent.py`) across all 9 modes for **both** `claude` and `agy`: `good`, `invent`, `rename`, `polarity`, `uncited`, `reword`, `fail`, `empty`, `hang` | `good` passes; `invent`→`unsupported-number`; `rename`→`unsupported-name`; `polarity`→`polarity-mismatch`; `uncited`→`untraced`; `reword`→warning only; `fail`/`empty`/`hang`→fallback to `rules` with warning (`fallback=True`), or `BackendError` exit 2 (`fallback=False`) | `integration` | `tests/integration/test_llm.py` |
| **TC-042** | `llm.status()` with fake CLIs: both ready, one missing, one timing out | Accurate per-backend `BackendAvailability` within timeout | `integration` | `tests/integration/test_llm.py` |
| **TC-043** | Corrupt/truncated PDF, corrupt DOCX zip, zip-bomb DOCX (`>50 MiB` uncompressed), malformed YAML/CSV, missing `.doc` system converter | Typed `InputError` or `SecurityError`; zero crashes | `torture` | `tests/torture/test_loader_faults.py` |
| **TC-044** | URL fetch failure (simulated timeout, `>10 MiB` stream, `>5` redirects via injected `url_opener`) | Typed `InputError` / `SecurityError`; bounded memory | `torture` | `tests/torture/test_loader_faults.py` |
| **TC-045** | Simulated mid-write `OSError` (disk full / permission denied) during `save_profile` | Original `<id>.yaml` byte-identical and uncorrupted; temp file cleaned up | `torture` | `tests/torture/test_atomic_save.py` |
| **TC-046** | Unhandled exception inside pipeline invoked through Web `App.handle` + pre-read `Content-Length > 256 KiB` on live socket | Returns HTTP `500` generic JSON (lock released for next request); oversized `Content-Length` rejected `413` pre-read | `torture` | `tests/torture/test_web_faults.py` |

### Dimension 6: Operational, Brand & Regression Ratchets

| ID | Scenario & Input | Expected Outcome | Tier | Target Test File |
|---|---|---|---|---|
| **TC-047** | Full `pipeline.generate` (`rules`) latency on 100-fact input + `conformance.score` on 5,000-word document | `generate` `<2.0s`; `score` `<1.0s`; bounded memory | `perf` | `tests/perf/test_latency_budgets.py` |
| **TC-048** | Example outputs `examples/outputs/*` vs. `scripts/build_examples.py --check` | Zero drift; deterministic reproduction | `system` | `tests/system/test_examples.py` |
| **TC-049** | `scripts/verify.sh --list` / `--status` and isolated fixture execution (guarded by `CASPER_IN_VERIFY` so zero recursion) | Exact one-line `PASS`/`FAIL` contract; `summary.tsv`, `report.md`, `junit.xml` valid | `smoke` | `tests/smoke/test_verify_gate.py` |
| **TC-050** | Casper Ghost Brand Kit (`scripts/build_brand.py --check`, `05-brand-assets.md`): logos, favicons (`16..1024`, `.ico`), 6 subsystem icons, die-cut stickers (`<g id="cutline">` + transparent RGBA corners `alpha == 0`), wallpapers (`1920x1080`, `2560x1080`, `2560x1440`, `3440x1440`, `3480x1440` dark & light), zero external `<image>`/`@import`, byte-sync `docs/brand/` ↔ `src/casper/web/static/img/` | Every required file exists, deterministic `--check` passes, exact pixel dimensions verified, sticker cutouts have transparent outer alpha & valid cutline path | `smoke` | `tests/smoke/test_brand.py` |

## 2. Threat & Failure Model

| Threat / Failure Mode | Surface / Stage | Likelihood | Impact | Concrete Mitigation | Enforcing Tests |
|---|---|---|---|---|---|
| **Private data (`email`, `consent`, `.local.yaml`) leaked to git, temp file, or external CLI prompt** | `layers.py`, `llm.py`, `.gitignore` | Med | High | `.local.yaml` gitignored & created atomically via `os.open(..., 0o600)`; `build_prompt` uses strict allowlist excluding `author` block and `local*` provenance; secret scan in `verify.sh`. | `TC-030`, `TC-038` |
| **External CLI (`claude`/`agy`) hallucinates numbers/signs, names (incl. sentence-initial), or flips meaning** | `llm.py` → `validator.py` | High | High | Mandatory `[fNNN]` citations; signed `unsupported-number`, full-sentence `unsupported-name`, `untraced`, and per-fact `polarity-mismatch` are hard `ERROR`s. | `TC-029`, `TC-041` |
| **External CLI executes workspace tools or mutates repo** | `llm.py` | Low | High | Non-interactive print flags (`-p --output-format text`), zero force/write flags, fresh empty temp `cwd`, `stdin=DEVNULL`, minimal env allowlist, hard timeout. | `TC-041` |
| **Unsolicited CTA hallucinated by heuristic `ask` cue** | `facts.py` → `planner.py` | High | Med | Dropped `"review"` cue; require explicit request phrasing, key/heading, or inline `[ask]` tag; pre-write `extract_facts` + `fact_overrides`. | `TC-020`, `TC-011` |
| **SSRF / local service probing via URL loader or 30x redirects** | `loaders/` | Med | High | Strict `http`/`https` allowlist; reject private/loopback/link-local/reserved IPs on initial fetch AND every manual redirect hop (max 5). | `TC-034`, `TC-044` |
| **CSRF, DNS rebinding, or remote exposure on web server** | `web/server.py` | Med | High | Hard `127.0.0.1` bind check; strict `Host` loopback+port validation; `Origin` exact-match; `Sec-Fetch-Site in {"same-origin","none"}`; `application/json` required; `OPTIONS` rejected `405`. | `TC-032` |
| **XSS via untrusted notes in HTML format or Web UI** | `modalities.py`, `web/static/app.js` | Med | High | `html.escape` on all HTML output; CSP `default-src 'self'`; static JS uses `textContent` only (zero `innerHTML`). | `TC-033` |
| **Path traversal via author ID or `/static/*`** | `catalog.py`, `web/server.py` | Med | High | Web sets `allow_path=False` (strict regex → `403`); static resolver strips query/NUL/backslash/percent-encoded traversal and enforces `is_relative_to(static_root)` (`404`). | `TC-032` |
| **DoS via oversized HTTP body, zip-bomb DOCX, huge URL, or combinatorial variant explosion** | `web/server.py`, `loaders/`, `realizer.py` | Med | Med | Pre-read `Content-Length <= 256 KiB` + socket timeout; `40k`/`60k` char caps; `lock.acquire(timeout=30)` → `503`; 10 MiB URL cap; 50 MiB DOCX cap; direct-index sampling above 512 variants. | `TC-025`, `TC-026`, `TC-039`, `TC-043`, `TC-046` |
| **Clobbering hand-edited profile or half-written YAML on crash** | `profile.py` | Med | Med | `body_sha256` checked before analysis (exit 3 unless `--force` + `.bak`); atomic temp-file + `fsync` + `os.replace`. | `TC-031`, `TC-045` |
| **Hidden coupling between writer rules and validator allow-list** | `rewrites.py`, `realizer.py`, `validator.py` | High | Med | Shared Rank-1 `rewrites.py` catalog with declared `added_tokens`; AST rank test forbids `validator -> realizer` imports. | `TC-005`, `TC-013`, `TC-029` |
| **Unintended `kill` of unrelated process via stale PID file** | `scripts/stop.sh` | Low | High | Verify `/proc/<pid>/cmdline` (NUL-delimited) matches `casper` + `serve` before sending `SIGTERM`. | `TC-040` |
| **Forbidden ML/LLM dependency drift** | `pyproject.toml`, `src/` | Low | High | Automated dependency + AST import gate blocks Hugging Face and LLM Python SDKs on every `--quick` run. | `TC-028` |

---

<!-- source: spec/04-implementation-plan.md -->

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

---

<!-- source: spec/05-brand-assets.md -->

# 05 — Casper Super-Cute Ghost Brand & Visual Asset Kit Contract

This document defines the complete visual identity contract for **Casper, the friendly ghostwriter**. All assets are generated deterministically by `scripts/build_brand.py` into `docs/brand/`, with the web-facing subset byte-synced into `src/casper/web/static/img/` and verified by `tests/smoke/test_brand.py` (`TC-050`) and `tests/smoke/test_hygiene.py` (`TC-004`).

## 1. Mascot Design Specification ("Super-Cute Casper Ghostwriter")

Every asset in the kit shares one unified, charming, mathematically crisp vector mascot — never generic clip-art and never inconsistent styles across sizes:

- **Silhouette & Expression:** Plump, rounded friendly ghost with a soft scalloped 3-wave bottom hem, gentle floating tilt (`-3°`), large expressive dark-navy eyes (`#0F172A`) with dual specular sparkle highlights (`#FFFFFF`), soft pastel rosy blush cheeks (`#FDA4AF`), and a warm curved smile.
- **Ghostwriter Prop:** Tiny tucked hand holding a glowing sky-cyan fountain pen / quill (`#38BDF8` / `#0284C7`) with a golden nib (`#FBBF24`) trailing 2–3 tiny floating sparkle stars and ink-drop accents — immediately communicating *friendly ghostwriter* without relying on unreadable tiny text.
- **Signature Palette:**
  - **Ghost Body:** Soft cloud white (`#F8FAFC` → `#E0F2FE` radial sheen), crisp outline (`#0F172A` on light surfaces; luminous `#38BDF8` glow rim on dark/obsidian surfaces).
  - **Primary Accent (Spectral Cyan):** `#38BDF8` / `#0EA5E9`
  - **Secondary Accent (Blush Pink):** `#FDA4AF`
  - **Nib / Sparkle Gold:** `#FBBF24`
  - **Dark Canvas (Obsidian Twilight):** `#0B0F1A` → `#131B2E` with subtle light-blue grid/starfield accents (`#1E293B` / `#38BDF8` at low opacity).
  - **Light Canvas (Paper Ivory):** `#F8FAFC` → `#EFF6FF` with crisp near-black ink (`#0F172A`).
- **Multi-Scale Legibility Invariants:**
  - All SVGs are 100% self-contained: **zero** external `<image>` URLs and **zero** webfont `@import` directives.
  - Icon viewBox `64x64` uses stroke widths `>= 2.0px` (`>= 12px` in `512x512` viewBox) so facial features, pen nib, and scalloped contour remain unmistakable down to `16x16` and `32x32`.
  - Square icons omit tiny tagline text; wordmarks appear only in wide horizontal lockups, hero banners, and wordmark stickers.

## 2. Deliverable Asset Manifest

All paths below are generated deterministically by `scripts/build_brand.py` (which supports `--check` for zero-drift verification).

### 2.1 Logos & Hero Banners (`docs/brand/`)

| File | Format | Exact Dimensions | Usage & Sync |
|---|---|---|---|
| `docs/brand/casper-mark.svg` | SVG | `512x512` viewBox | Primary square cute ghost mascot (no text); synced to `web/static/img/` |
| `docs/brand/casper-mark-512.png` | PNG (RGBA) | `512x512` | High-res square emblem; transparent background |
| `docs/brand/casper-mark-1024.png` | PNG (RGBA) | `1024x1024` | High-DPI master square emblem; transparent background |
| `docs/brand/casper-logo-light.svg` | SVG | `640x180` viewBox | Horizontal mascot + `CASPER` wordmark for light headers; synced to `web/static/img/` |
| `docs/brand/casper-logo-dark.svg` | SVG | `640x180` viewBox | Horizontal mascot + `CASPER` wordmark for dark footers/headers; synced to `web/static/img/` |
| `docs/brand/casper-hero.svg` | SVG | `1200x360` viewBox | Wide README & docs hero banner (obsidian twilight grid + cute ghost + title + subtitle) |
| `docs/brand/casper-hero.png` | PNG (RGBA) | `1200x360` | Rasterized hero banner for GitHub README & OpenGraph (`og:image`) |

### 2.2 Icons, Favicons & Subsystem Badges (`docs/brand/` & `docs/brand/icons/`)

| File | Format | Exact Dimensions | Notes |
|---|---|---|---|
| `docs/brand/favicon.svg` | SVG | `64x64` viewBox | Simplified crisp cute-ghost face (stroke `>=2px`); synced to `web/static/img/` |
| `docs/brand/favicon.ico` | ICO | `16x16, 32x32, 48x48` | Multi-resolution ICO; synced to `web/static/img/` |
| `docs/brand/favicon-16x16.png` | PNG (RGBA) | `16x16` | Browser tab icon; synced to `web/static/img/` |
| `docs/brand/favicon-32x32.png` | PNG (RGBA) | `32x32` | Standard favicon; synced to `web/static/img/` |
| `docs/brand/apple-touch-icon.png` | PNG (RGBA) | `180x180` | iOS/macOS touch icon with rounded tile background; synced to `web/static/img/` |
| `docs/brand/icon-192x192.png` | PNG (RGBA) | `192x192` | Web manifest / PWA icon; synced to `web/static/img/` |
| `docs/brand/icon-512x512.png` | PNG (RGBA) | `512x512` | App / plugin store icon; synced to `web/static/img/` |
| `docs/brand/icon-1024x1024.png` | PNG (RGBA) | `1024x1024` | High-DPI master app icon |
| `docs/brand/icons/icon-voice.svg` | SVG | `64x64` viewBox | Subsystem badge: Author Voice Fingerprint |
| `docs/brand/icons/icon-facts.svg` | SVG | `64x64` viewBox | Subsystem badge: Fact Extraction & Graph |
| `docs/brand/icons/icon-plan.svg` | SVG | `64x64` viewBox | Subsystem badge: Audience & Structure Planner |
| `docs/brand/icons/icon-validate.svg` | SVG | `64x64` viewBox | Subsystem badge: Fidelity Validator |
| `docs/brand/icons/icon-format.svg` | SVG | `64x64` viewBox | Subsystem badge: Multi-Modality Formatter |
| `docs/brand/icons/icon-cli-writer.svg` | SVG | `64x64` viewBox | Subsystem badge: Claude / Antigravity CLI Writer |

### 2.3 Die-Cut Stickers with Border Cutouts (`docs/brand/stickers/`)

All die-cut stickers feature a uniform, smooth contoured **white vinyl offset border** (`~8%` contour padding around the mascot, quill, sparkles, and optional wordmark) plus an explicit vector cutline group (`<g id="cutline">` in SVG, crisp magenta/dashed print-guide optional layer or clean kiss-cut stroke) and **strictly transparent background outside the border cutout** (`alpha == 0` on all 4 corners and outer margins of every PNG).

| File | Format | Exact Dimensions | Specification |
|---|---|---|---|
| `docs/brand/stickers/casper-sticker-diecut.svg` | SVG | `1500x1500` viewBox | Cute ghost + fountain pen die-cut sticker with white vinyl offset contour and `<g id="cutline">` vector path (Cricut/Silhouette/Sticker Mule ready) |
| `docs/brand/stickers/casper-sticker-diecut.png` | PNG (RGBA) | `1500x1500` (300 DPI @ 5×5 in) | Transparent-background print-ready die-cut sticker with crisp white border cutout and subtle outer edge definition |
| `docs/brand/stickers/casper-sticker-diecut-1024.png` | PNG (RGBA) | `1024x1024` | Digital chat/Slack/Discord sticker with white die-cut border cutout |
| `docs/brand/stickers/casper-sticker-wordmark-diecut.svg` | SVG | `1800x1200` viewBox | Cute ghost + `"CASPER"` + `"friendly ghostwriter"` contoured die-cut sticker with `<g id="cutline">` |
| `docs/brand/stickers/casper-sticker-wordmark-diecut.png` | PNG (RGBA) | `1800x1200` (300 DPI @ 6×4 in) | Print-ready transparent-background wordmark die-cut sticker |
| `docs/brand/stickers/casper-sticker-sheet.svg` | SVG | `2550x3300` viewBox (8.5×11 in @ 300 DPI) | Print-ready multi-sticker kiss-cut sheet (mascot stickers in 3 sizes + wordmark stickers + mini ghost icons) with `<g id="cutline">` |
| `docs/brand/stickers/casper-sticker-sheet.png` | PNG (RGBA) | `2550x3300` | Rasterized transparent-background sticker sheet |

### 2.4 Screen Backgrounds / Wallpapers (`docs/brand/wallpapers/`)

Generated in standard desktop and ultrawide resolutions **up to and including `3480x1440`**, in both **Dark Twilight Obsidian (`dark`)** and **Clean Paper Sky (`light`)** themes. Composition scales cleanly to each aspect ratio (16:9 and ~21:9/ultrawide) without stretching the mascot — placing the super-cute ghostwriter mascot with subtle glowing constellation/notebook-grid geometry and balanced desktop-icon negative space on the left/right margins.

| Resolution | Aspect Class | Dark Variant | Light Variant |
|---|---|---|---|
| **`1920x1080`** | FHD 16:9 | `casper-wallpaper-dark-1920x1080.{svg,png}` | `casper-wallpaper-light-1920x1080.{svg,png}` |
| **`2560x1080`** | Ultrawide 21:9 | `casper-wallpaper-dark-2560x1080.{svg,png}` | `casper-wallpaper-light-2560x1080.{svg,png}` |
| **`2560x1440`** | QHD 16:9 | `casper-wallpaper-dark-2560x1440.{svg,png}` | `casper-wallpaper-light-2560x1440.{svg,png}` |
| **`3440x1440`** | UWQHD 21:9 | `casper-wallpaper-dark-3440x1440.{svg,png}` | `casper-wallpaper-light-3440x1440.{svg,png}` |
| **`3480x1440`** | Super-Wide (exact requested max) | `casper-wallpaper-dark-3480x1440.{svg,png}` | `casper-wallpaper-light-3480x1440.{svg,png}` |

## 3. Generator Contract (`scripts/build_brand.py`)

```text
Usage: python3 scripts/build_brand.py [--check]
```

- **Pure deterministic generation:** Uses pure Python SVG generation + local rasterization (e.g., `cairosvg` / `rsvg-convert` / `resvg` / `Pillow` fallback renderer with zero network calls) to produce identical bytes across runs (no embedded timestamps in PNG `tEXt` chunks or SVG metadata).
- **Web static sync:** Copies `casper-mark.svg`, `casper-logo-light.svg`, `casper-logo-dark.svg`, `favicon.svg`, `favicon.ico`, `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png`, `icon-192x192.png`, `icon-512x512.png` into `src/casper/web/static/img/` byte-for-byte.
- **`--check` mode:** Regenerates into a temporary directory and compares SHA-256 hashes of every asset in `docs/brand/` and `src/casper/web/static/img/`, exiting `0` only if every file matches byte-for-byte.
- **Automated verification (`TC-050`):**
  1. Verifies every required file in §§2.1–2.4 exists and passes `build_brand.py --check`.
  2. Parses every SVG via XML parser: confirms valid XML, zero external `<image href="http...">` or `@import`, and `<g id="cutline">` present in all die-cut sticker SVGs.
  3. Opens every PNG/ICO via `Pillow`: confirms exact `(width, height)` pixel dimensions (including exact `3480x1440` wallpapers and `1500x1500`/`1800x1200`/`2550x3300` stickers) and confirms die-cut sticker PNGs are `RGBA` with transparent corner pixels (`alpha == 0`) outside the white vinyl border cutout.
  4. Confirms byte-identity between `docs/brand/` and `src/casper/web/static/img/`.
