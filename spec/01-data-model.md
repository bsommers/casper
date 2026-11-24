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
