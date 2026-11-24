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
