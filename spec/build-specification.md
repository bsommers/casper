# Casper — Draft Build Specification

> **Status:** Draft  
> **Product:** **Casper**, the friendly ghostwriter  
> **Source:** Ordered and adapted from the 11 screenshots in `raw_inputs/` (external brand references removed; CLI writer backends targeting Claude Code CLI and Antigravity/`agy` CLI).

A distilled specification of everything to build for **Casper, the friendly ghostwriter**, written so that someone with this document and an empty repository can recreate it. It is also the document to review before the next phase: Section 12 lists the architectural choices that most deserve a second look.

Detail lives elsewhere and is linked: [SPEC.md](../SPEC.md) (full specification), [adr/](../docs/adr/README.md) (decisions), [data-model.md](../docs/data-model.md) (field tables), [api-reference.md](../docs/api-reference.md).

## 1. Intent and hard constraints

**Product.** Turn notes into a draft in a named author's voice, for a chosen reader, in a chosen format, with every sentence traceable to a fact in the notes. Local by default.

| Constraint | Source |
|---|---|
| No Hugging Face, no Python LLM client packages. Opt-in exception: shell out to the Claude Code CLI (`claude`) or Antigravity CLI (`agy`) | ADR 0001, 0010; enforced by `tests/test_constraints.py` |
| Deterministic by default: same notes, profile, libraries and seed give identical output | ADR 0009 |
| Nothing is invented: every non-closing sentence cites facts; numbers and names must come from them | ADR 0009 |
| Private data (email, consent) never in tracked files | ADR 0005 |
| Web page binds to localhost only | ADR 0011 |
| Stack: Python 3.11 to 3.13, spaCy with the pinned `en_core_web_sm` wheel (from the spaCy GitHub releases), scikit-learn, NetworkX, PyYAML, BeautifulSoup, lxml, pypdf, python-docx, striprtf, pytest | `pyproject.toml` |

## 2. Architecture in one page

```text
interfaces    cli.py            web/server.py (+ static UI)       Python: pipeline.generate
                  \                 |                               /
orchestration                   pipeline.generate(Brief) -> Result
                                    |
stages     Ingest -> Plan -> Adapt -> Realize -> Validate -> Format
           facts.py  planner.py       realizer.py validator.py modalities.py
                                      or llm.py (claude / agy CLI)
models     documents.py (Document, Block)    libraries.py (Persona, Structure, Modality, Glossary)
voice      features/* -> profile.py (build/save/load) -> layers.py (merge) -> conformance.py (score)
data       src/casper/data/{personas,structures,modalities,glossaries}/*.yml, phrasebank.yaml, lexicons.yaml
           authors/<id>.yaml + .curated.yaml + .local.yaml
```

Rules of the shape:

1. Dependencies point downward only. Stages never import interfaces.
2. Each stage takes one typed object and returns the next (`FactModel`, `Plan`, `Draft`, `Validation`, text).
3. Behavior a person may want to tune is YAML, not code.
4. Guarantees are validator **errors**; quality signals are **warnings**.
5. Anything that leaves the machine sits behind an explicit opt-in and a fallback.

## 3. Repository layout to create

```text
src/casper/       __init__.py (lazy exports) cli.py pipeline.py facts.py planner.py realizer.py llm.py
                  validator.py modalities.py libraries.py conformance.py profile.py layers.py catalog.py
                  documents.py parsing.py loaders/ features/ data/ web/{server.py,static/}
tests/            one file per module, fixtures/status_notes.md, golden/, fakes/fake_agent.py
authors/  examples/  docs/  spec/  scripts/  input/  output/
scripts/          start.sh stop.sh build_spec.py build_brand.py build_examples.py calibrate_conformance.py capture_screenshots.mjs
.gitignore        .venv, caches, input/*, output/* (keep READMEs), authors/*.local.yaml, *.bak, *.tmp
pyproject.toml    console script `casper = casper.cli:main`; hatch wheel packages src/casper
```

## 4. Core data types

```python
@dataclass Block:     kind, text, level=0, links=0, emphasis_lead=False     # kinds: title heading paragraph list_item quote code summary audience resources
@dataclass Document:  source, format, title, authors, published, modified, canonical_url, description, blocks, sha256, notes
@dataclass Fact:      id("f001"), kind, text, source, order, entities, metrics, dates, owners, salience
@dataclass Persona:   id, kind(source|target), priorities, vocabulary_include, vocabulary_avoid, detail_depth(low|medium|high),
                      jargon_level(low|medium|high), framing_patterns, typical_concerns, cta_styles, section_priority
@dataclass Section:   name, purpose, fact_kinds, required, min_words, max_words, heading
@dataclass Structure: id, goal, sections, compatible_modalities, default_target_personas
@dataclass Modality:  id, markup(markdown|slack|html|plain), max_words, max_chars, title, headings, bullets, description
@dataclass Glossary:  plain{term:replacement}, preferred{variant:house form}, banned[]
@dataclass Sentence:  text, fact_ids, frame     # frame=True: closing line, no facts, asserts nothing
@dataclass Draft:     sections[DraftSection(name, heading, sentences)], title, warnings, candidates_considered, backend, meta
@dataclass Constraints: max_words, max_chars, banned, candidates=8, seed=0
@dataclass Brief:     structure, modality, source, target, author, inputs, notes, topic, seed, candidates, min_voice, banned,
                      project_dir, authors_dir, backend="rules", fallback=True, timeout=90, model=None
@dataclass Result:    text, draft, validation, fact_trace, record, facts
```

Personas are keyed by `(kind, id)` so `product_owner` exists as both a source and a target. The fact kinds are exactly: `status`, `progress`, `risk`, `next_step`, `decision`, `background`, `detail`, `metric`, `ask`.

## 5. Stage specifications

### 5.1 Loaders and the document model

One `load_document(path_or_url)` and `load_bytes(data, name)` dispatch on content, not only extension: PDF, RTF and OLE `.doc` by magic bytes; `.docx` by zip header; HTML by content type or extension; everything else as text. Formats: HTML (JSON-LD and meta tags for title, author and dates; main-content extraction; headings, paragraphs, list items, quotes, code), Markdown and text (front matter, headings, lists, inline-markup removal), LaTeX (own extractor), DOCX (`python-docx`), PDF (`pypdf`), RTF (`striprtf`; one paragraph per line), DOC and ODT (system converter if present). URLs: `http` and `https` only, 30 second timeout, size cap. Blocks tagged as `summary`, `audience` or `resources` are excluded from voice statistics. `*_files` asset folders are skipped.

### 5.2 Author fingerprint (profile build)

`build_profile(id, name, inputs, aliases, strict_authors, min_words=150)` loads each source, drops those under `min_words` of prose, records byline matches, parses with spaCy (`load_nlp()`, NER off), and runs `features.analyze`:

| Group | Contents |
|---|---|
| `sentences` | length distribution (mean, median, p10, p90, stdev), short rate (8 words or fewer), long rate (30 or more), burstiness cv, passive rate, subordinate clauses and commas per sentence, fragment, question and exclamation rates, start-of-sentence classes, top first words |
| `paragraphs` | sentences and words per paragraph, single-sentence rate, long-paragraph rate |
| `lexical` | words, Flesch-Kincaid grade, reading ease, mean word length, long-word rate (7 or more letters), acronyms per 1,000 |
| `voice` | person (I, we, you, they) per 1,000, contractions, negations, punctuation per 1,000 (em dash, colon, semicolon, parentheses, quotes), commas per 1,000, Oxford comma, lexicon rates (transitions, intensifiers, hedges, from `data/lexicons.yaml`), contrast frames ("not X; it is Y"), acronym introductions |
| `typography`, `headings`, `lists`, `structure` | quote style, links, heading case and length, list lead-ins, document length, sections, summary and closing patterns |
| `function_word_per_1k` | top 60 function words |
| `signature`, `exemplars` | recurring phrases, function-word-bounded phrases, sentence frames; a few of the author's own openers, closers and short lines |
| `stability` | per-document min, max and stdev for the 32 scored scalars (`features.STABILITY_KEYS`) |

Output: `authors/<id>.yaml` with `schema_version`, `author` (id, display name, aliases; **no email**), `generated` (tool, date, model, `corpus_sha256`, `body_sha256`), `corpus`, `style_guide` (list of `{id, area, rule}`, ids equal to area names, rules produced by deterministic templates from the numbers), the groups above, and `sources` (title, URL or file, byline, `byline_matches_author`, prose words, SHA-256). Save is atomic (temp file then rename). `body_sha256` is a hash of the canonical JSON of the body without that field.

### 5.3 Profile layers (ADR 0005)

Files: `<id>.yaml` generated, `<id>.curated.yaml` human and tracked, `<id>.local.yaml` human, git-ignored, mode 0600. `resolve(generated, curated, local, overlays)`:

- mappings merge recursively; scalars: later layer wins; lists change only through `{$add, $remove, $replace}`;
- `style_guide` edits are keyed by rule id: a string replaces the rule text, `$remove` deletes, a mapping with `area` and `rule` adds, anything else is an orphan;
- order: generated, curated, local, then overlay sections named by the caller (the output format) from curated then local;
- result carries `provenance`: dotted path to layer name.

`save_profile` refuses (exit code 3 in the CLI, checked before analysis) when the existing file has a recorded `body_sha256` that no longer matches, unless `--force`, which writes `.bak` first. Legacy files without a hash are overwritten. `drift_report` lists orphaned curated edits, pins naming unscored features, and pins whose value is more than one spread (stdev, floored at 10% of the value) from the rebuilt value. `author build --email` writes only to the local layer.

### 5.4 Voice conformance score (ADR 0006)

`score(profile, document, nlp) -> Report`. Method:

1. Run the same extraction on the candidate; `words` below 1 or no sentences raises `ValueError`.
2. For each of 32 scored features (table below) compute `sigma = max(stability.stdev, floor, 0.1 * |author value|) * widen`, where `widen = min(1.5, max(1, sqrt(avg_doc_words / candidate_words)))`. A curated **pin** replaces the author value and, if given, the stdev.
3. `z = |candidate - author| / sigma`; feature score `exp(-z^2 / 4.5)` (1 sd gives 0.80, 2 sd 0.41, 3 sd 0.14).
4. Dimension score is the weight-averaged feature score. Add `function_words`: cosine similarity of candidate and profile function-word vectors, mapped `(cos - 0.85) / (0.97 - 0.85)` clipped to 0..1. Add `structure` only if the candidate has at least 2 headings and the profile has headings: mean of a heading-density term and a heading-case-style term.
5. Overall = 100 times the weighted **geometric** mean of dimensions (dimension scores floored at 0.02), so one badly wrong dimension cannot hide.
6. Bands: 80 strong match, 65 close, 45 partial, below that different voice. Confidence: high at 1,000 words or more, medium at 250 or more, else low.
7. Output also lists up to six "largest gaps" (features scoring under 0.5, worst first, in words with the author's value and spread) and which signature phrases and frames appear (reported, not scored).

| Feature | Dimension | Weight | Floor | Profile path |
|---|---|---|---|---|
| `mean_sentence_length` | rhythm | 2.0 | 2.0 | `sentences.length_words.mean` |
| `short_sentence_rate` | rhythm | 1.0 | 0.04 | `sentences.short_rate_le8` |
| `long_sentence_rate` | rhythm | 1.0 | 0.04 | `sentences.long_rate_ge30` |
| `sentence_length_cv` | rhythm | 0.7 | 0.08 | `sentences.burstiness_cv` |
| `passive_rate` | rhythm | 1.0 | 0.08 | `sentences.passive_rate` |
| `commas_per_sentence` | rhythm | 0.7 | 0.25 | `sentences.commas_per_sentence` |
| `subordinate_clauses_per_sentence` | rhythm | 0.7 | 0.2 | `sentences.subordinate_clauses_per_sentence` |
| `fragment_rate` | rhythm | 0.7 | 0.03 | `sentences.fragment_rate` |
| `question_rate` | rhythm | 0.7 | 0.02 | `sentences.question_rate` |
| `exclamation_rate` | rhythm | 0.7 | 0.01 | `sentences.exclamation_rate` |
| `conjunction_start_rate` | openers | 0.7 | 0.03 | `sentences.starts.conjunction_rate` |
| `pronoun_start_rate` | openers | 0.8 | 0.06 | `sentences.starts.pronoun_rate` |
| `transition_start_rate` | openers | 0.8 | 0.05 | `sentences.starts.adverb_or_transition_rate` |
| `sentences_per_paragraph` | paragraphs | 1.5 | 0.6 | `paragraphs.sentences_per_paragraph.mean` |
| `single_sentence_paragraph_rate` | paragraphs | 1.0 | 0.1 | `paragraphs.single_sentence_rate` |
| `flesch_kincaid_grade` | register | 2.0 | 1.2 | `lexical.flesch_kincaid_grade` |
| `mean_word_length` | register | 1.0 | 0.15 | `lexical.mean_word_length` |
| `long_word_rate` | register | 0.7 | 0.04 | `lexical.long_word_rate_ge7` |
| `acronyms_per_1k` | register | 0.8 | 5.0 | `lexical.acronyms_per_1k` |
| `first_person_singular_per_1k` | point_of_view | 1.2 | 1.5 | `voice.person_per_1k.first_singular` |
| `first_person_plural_per_1k` | point_of_view | 1.2 | 2.5 | `voice.person_per_1k.first_plural_inclusive` |
| `second_person_per_1k` | point_of_view | 1.2 | 2.5 | `voice.person_per_1k.second` |
| `contractions_per_1k` | point_of_view | 1.2 | 2.5 | `voice.contractions_per_1k` |
| `em_dashes_per_1k` | punctuation | 1.0 | 1.5 | `voice.punctuation_per_1k.em_dash` |
| `colons_per_1k` | punctuation | 1.0 | 3.0 | `voice.punctuation_per_1k.colon` |
| `semicolons_per_1k` | punctuation | 0.7 | 1.5 | `voice.punctuation_per_1k.semicolon` |
| `parentheses_per_1k` | punctuation | 0.7 | 2.0 | `voice.punctuation_per_1k.parenthetical` |
| `commas_per_1k` | punctuation | 0.7 | 8.0 | `voice.commas_per_1k` |
| `transitions_per_1k` | rhetoric | 0.8 | 3.0 | `voice.lexicon_per_1k.transitions` |
| `intensifiers_per_1k` | rhetoric | 0.8 | 3.0 | `voice.lexicon_per_1k.intensifiers` |
| `hedges_per_1k` | rhetoric | 0.8 | 3.0 | `voice.lexicon_per_1k.hedges` |
| `contrast_frames_per_1k` | rhetoric | 0.8 | 1.0 | `voice.rhetoric.contrast_frames_per_1k` |

Dimension weights: rhythm 1.5, openers 0.7, paragraphs 0.8, register 1.2, point_of_view 1.2, punctuation 1.0, rhetoric 0.9, function_words 1.2, structure 0.8.

**Calibration** (`scripts/calibrate_conformance.py`): leave one article out, build the profile from the rest, score the held-out article and other texts. Measured: held-out articles 74 to 87; other registers (casual chat, legalese, README, this spec) 18 to 61; other HiveMQ authors (same house style) 74 to 91, which overlaps. The thresholds are provisional.

### 5.5 Libraries

`load_libraries(project_dir=None)` reads `data/{personas,structures,modalities,glossaries}/*.yaml`, then the same folders under `project_dir` (override by id; personas by kind and id), validates (kinds, depth and jargon enums, markup, every structure's modalities and default targets exist), and returns `Libraries` plus a `digest` (hash of every file read). `check_combo(structure, modality, target)` raises `LibraryError` listing valid choices. Shipped content: 10 personas, 3 structures, 5 modalities, one glossary, `phrasebank.yaml` (closing lines by style). Exact values are in [data-model.md](../docs/data-model.md).

### 5.6 Ingest and fact model (`facts.py`)

`ingest(inputs, notes, nlp)` reads each file (`.csv`, `.yaml` and `.yml` by their own parsers; everything else via the loaders) plus inline notes, and returns a `FactModel` or raises `ValueError` ("Nothing to write from" or "No facts could be extracted"). For Markdown and text, `"Key: value"` lines whose key is one of `status`, `state`, `owner`, `risk(s)`, `blocker`, `next`, `next step(s)`, `ask`, `request`, `decision`, `progress`, `done`, `background`, `context`, `metric` are pulled out first (the loaders collapse line breaks) and restated using only the source's words ("The status is on track."). Each remaining sentence gets a kind by this order: explicit key; nearest heading (regexes in `_HEADING_KIND`); keyword cues (`_CUES`: ask, risk, decision, progress, next_step, status); default (`background` for the first paragraph when no heading applies, else `detail`). Per fact: entities (`ORG`, `PRODUCT`, `GPE`, `FAC`, `EVENT`, `WORK_OF_ART`, `LAW`), owners (`PERSON`, plus the `Owner` key), figures (numbers with units or currency), dates; `salience = 1.0 + 0.4 (figures) + 0.2 * min(entities, 2) + 0.2 (dates) + 0.3 (status)`. Duplicates (same normalized text) are dropped. The NetworkX `DiGraph` has fact nodes, entity, owner, metric and date nodes, `mentions` edges and `follows` edges in reading order. Loaded with `load_nlp(ner=True)`.

### 5.7 Plan and adapt (`planner.py`)

`plan_structure(model, structure)`: for each section in order, take facts of the accepted kinds sorted by salience then order, each fact used once. Required sections with no facts, and facts that fit no section, are reported as warnings; nothing is filled in. `adapt(plan, source, target, glossary)`:

| Rule | Behavior |
|---|---|
| Depth cap | Per section keep the top N by salience plus 0.3 if the fact mentions a word (4 or more letters) from the source persona's priorities, concerns or vocabulary; N is 1, 3 or 6 for the target's low, medium or high; kept facts are narrated in source order; the rest are counted in a warning |
| Section order | Sections listed in the target's `section_priority` move first, in that order |
| Substitutions | Target `jargon_level: low` adds the glossary's `plain` map; the `preferred` map always applies |
| Closing | Only if some kept fact is an `ask`: the first style in both personas' `cta_styles`, else the target's first, else the source's |

### 5.8 Realize (`realizer.py`)

`RuleBasedRealizer.realize(plan, voice, constraints)`: for each non-empty section, build variants per fact (plain, contracted, expanded; for facts after the first, a transition opener from a fixed table such as "Also," or "Next,"), take the product (up to 512 combinations, else a seeded sample that always includes the plain variant), optionally merge the first two short sentences with a semicolon (not when the second already starts with a transition), cap at `candidates`, shuffle with `random.Random(seed)`, then pick the variant with the highest `conformance.score` over the draft so far plus the candidate (first wins ties; without a profile the first variant is used). The closing line is picked from `phrasebank.yaml` by the seeded RNG. `fit_to_limits(draft, plan, constraints)` then drops the lowest-salience cited fact (never the first fact of a required section) until the word and character limits hold, removes the closing line if no ask remains, and warns. Glossary substitution (`substitute`) is whole-word, case-preserving, longest term first.

### 5.9 Claude and Antigravity/agy CLI writers (`llm.py`, ADR 0010)

`CliAgentRealizer(backend, timeout, model, runner).realize(...)` (supporting `backend="claude"` for Claude Code CLI and `backend="agy"` for Antigravity CLI):

- Prompt contains only: rules (use only these facts; every sentence ends with `[fNNN, ...]`; keep numbers and names exact; one `## heading` block per section; no fences), perspective and audience with avoided words, glossary replacements, length limits, up to 8 style-guide rule texts and up to 6 exemplar sentences, then the sections with `[id] fact text`. It never includes the local layer or the profile's author block.
- Invocation: runs the selected CLI non-interactively in a fresh empty temporary directory, stdin closed, no destructive/force flag, `timeout` seconds (default 90; 120 from the web page):
  - **Claude (`claude`)**: `claude -p --output-format text [--model M] <prompt>` (non-interactive print mode, read-only / no workspace mutation). `ANTHROPIC_API_KEY` (if set) is passed through the environment only. `CASPER_CLAUDE_CLI` and `CASPER_CLAUDE_MODEL` override the executable and model.
  - **Antigravity (`agy`)**: `agy -p --output-format text [--model M] <prompt>` (non-interactive print/ask mode, read-only / no workspace mutation). Configured Antigravity credentials (if set) are passed through the environment only. `CASPER_AGY_CLI` and `CASPER_AGY_MODEL` override the executable and model.
- Parsing: `## Heading` starts a section; a trailing `[f001, f002]` closes a sentence; sentences without one are kept uncited and fail validation. Glossary replacements are re-applied; the closing line is added from the phrase bank; `fit_to_limits` runs.
- Failure (missing binary, not signed in, timeout, empty): raises `BackendError`; `pipeline.generate` falls back to the rule-based writer, adds a warning `"<Backend> backend unavailable (...) Used the rule-based writer instead."`, and records requested and used backends. `fallback=False` re-raises.
- `llm.status()` checks availability of the configured CLIs (`claude` and `agy`, 20 second limit each) and reports readiness per backend.

### 5.10 Validate (`validator.py`)

| Code | Level | Rule |
|---|---|---|
| `frame-with-facts`, `untraced`, `unknown-fact` | error | frames carry no ids; other sentences must cite existing facts |
| `unsupported-number` | error | every number in a sentence appears in its cited facts |
| `unsupported-claim` | error (built-in writer) / warning `reworded` (Claude / Antigravity `agy`) | words longer than 3 letters not in the cited facts, the glossary replacements, the opener table, contraction forms or a small stop list |
| `unsupported-name` | error (Claude / Antigravity `agy` only) | a capitalized mid-sentence word not in the cited facts |
| `too-long`, `too-long-chars`, `empty` | error | modality limits; non-empty draft |
| `banned-term` | error | glossary `banned` plus the brief's words, whole-word, case-insensitive |
| `glossary` | error | a `preferred` variant still present |
| `persona-avoid`, `persona-jargon`, `persona-depth`, `persona-order` | warning | target's avoided words, leftover plain-glossary terms for low jargon, facts per section over the depth cap, section order against `section_priority`; persona score is the share of checks passed, times 100 |
| `voice-low-confidence`, `voice-unscorable` | warning | short or unscoreable draft |
| `voice-below-threshold` | error | score below `min_voice` (when set) |
| `plan` | warning | planner and realizer warnings pass through |

`Validation.ok` is true when there are no errors. The draft is always returned.

### 5.11 Format (`modalities.py`)

Formatting never changes wording. `plain`: sentences joined by spaces. `html`: complete page, escaped text, `h1` title, `h2` headings, `ul` when bulleted. `markdown`/`slack`: title as `# ...` when the format has one; headings as `## ` (long form), `**bold**` (short form) or `*bold*` (Slack, converting `**` to `*`); sections with two or more sentences become bullets (`-` or the bullet character) when the format has bullets; the closing line is never bulleted.

### 5.12 Pipeline and reproducibility record (`pipeline.py`)

`generate(brief, libs=None, nlp=None)`: load personas, structure, modality; load the author profile **resolved** with the output format as overlay (`find_profile` by id unless the author is a path); `ingest`; `plan_structure`; `adapt`; realize with `Constraints(max_words, max_chars, banned + glossary banned, candidates, seed)`; `validate`; `format_draft`; build `fact_trace` (per sentence: section, text, frame, cited facts with kind, source and text) and the record: tool version, seed, candidates, selectors, SHA-256 of each input, facts digest, config digest, author corpus hash, output hash, backend block (requested, used, deterministic, plus model and prompt and response hashes for Claude / Antigravity `agy`), and a 16-character hash of the record. Unknown backend raises `ValueError`.

## 6. Interfaces

**CLI** (`casper`): `write` (options in [using.md](../docs/using.md); stdout draft, stderr scores and warnings; exit 0, 1 failed checks, 2 bad input; `--out` also writes `.trace.json`; `--brief` YAML; `--backend rules|claude|agy`; `--no-fallback`), `serve`, `author build|inspect|show [--resolved]|score [--raw]|list|diff`; build exits 3 on a hand-edited profile.

**Web** (`web/server.py`, standard library `ThreadingHTTPServer`, default port 8731): `GET /`, `/static/*`, `/api/options`, `/api/backend-status`; `POST /api/generate`, `/api/score`, `/api/token` (always 501). `App.handle(method, path, headers, body)` is a pure function used by tests; `Handler` adapts it. Rules: bind to `127.0.0.1` only (`make_server` refuses others); `Host` must be a loopback name with the server's port; `Origin` if present must match; `Sec-Fetch-Site: cross-site` rejected; POST needs `application/json`, body at most 256 KB, notes at most 40,000 characters, text to score at most 60,000; unknown fields rejected; authors by catalog id only, never paths; one pipeline run at a time (lock); internal errors return a generic message; headers: CSP `default-src 'self'` with no inline script or style, `nosniff`, `no-referrer`, `no-store`. Generate responses add `facts` and `backend`.

**Front end** (`web/static`): single page, no framework, no build step; all server data written with `textContent`; tabs Write, Check a draft, About; format choices disabled when incompatible with the message type; Claude and Antigravity (`agy`) backend readiness badges from `/api/backend-status`; disabled API token field; result chips, three result views (draft, where each sentence came from, checks), Copy and Download. Styling: `theme.css` CSS variables defining Casper's own clean UI theme (sticky header, high-contrast near-black text, neutral hero band, pill buttons, system sans-serif, dark footer); `static/img/` holds byte-identical copies of the Casper mark, favicon and logos from `docs/brand/` (a test enforces this).

**Scripts**: `start.sh` (creates `.venv` with `uv`, installs when imports fail, refuses a busy port or a running background server, warns when `authors/` is empty, `--background --open --port --no-install`), `stop.sh` (verifies the pid is a Casper process before killing).

## 7. Decisions on record

| ADR | Decision | Status |
|---|---|---|
| 0001 | No LLM or Hugging Face; rule-based realization (amended by 0010) | accepted |
| 0002 | Author profiles are YAML, one file each | accepted |
| 0003 | `SPEC.md` generated from `spec/*.md` | accepted |
| 0004 | `input/` and `output/` git-ignored | accepted |
| 0005 | Generated, curated and local profile layers | **proposed** |
| 0006 | Voice score is profile-relative and deterministic | accepted |
| 0007 | Catalog-relative scoring once there are three authors | **proposed** |
| 0008 | v1 scope: 3 structures, 5 formats, 10 personas | accepted |
| 0009 | Every sentence cites facts; variants ranked by voice score | **proposed** |
| 0010 | Optional Claude Code (`claude`) and Antigravity (`agy`) CLI writers, off by default | accepted |
| 0011 | Web page is a localhost standard-library server | accepted |

Process: new ADR from `docs/adr/TEMPLATE.md`, starts `proposed`, `accepted` only with the user's agreement and a real "Enforced by"; append-only; `tests/test_adr.py` keeps the register in sync.

## 8. Test strategy

195 tests, about 15 seconds, no network and no real model. Guarantees are tested by trying to break them (invented number, banned word, hand-edited profile, path input, cross-origin request, private data in the prompt). Golden files for every valid structure and format pair (`tests/golden/`, regenerate with `CASPER_UPDATE_GOLDEN=1`); example outputs (`examples/outputs/`); a stand-in Claude / Antigravity (`agy`) CLI (`tests/fakes/fake_agent.py`, modes `good`, `invent`, `rename`, `uncited`, `reword`, `fail`, `empty`, `hang`); a real socket round trip; documentation hygiene (links, index, diagrams, commands). Full table: [testing.md](../docs/testing.md).

## 9. Build order to recreate

1. Scaffold, `pyproject.toml`, `.gitignore`, `AGENTS.md`, spec and ADR machinery (`build_spec.py`, `test_spec.py`, `test_adr.py`, `test_constraints.py`).
2. Document model and loaders; spaCy parsing; lexicons.
3. Feature extractors, `profile.py`, `author build|show|inspect`; build a profile from real samples.
4. `conformance.py`, `STABILITY_KEYS`, `author score`, calibration script.
5. `layers.py`, body hash, atomic save, `--force`, local email, drift report.
6. `libraries.py` and the YAML data; `facts.py`; `planner.py`.
7. `realizer.py`, `validator.py`, `modalities.py`, `pipeline.py`, `write`; goldens.
8. `catalog.py`, `author list|diff`.
9. `llm.py` (Claude `claude` and Antigravity `agy` CLI backends) and the fake CLI; backend switch in the pipeline.
10. `web/server.py`, static UI, brand images, `serve`; screenshots.
11. Start and stop scripts, examples, documentation set, brochure.

## 10. Verification: how to know the rebuild is right

```bash
.venv/bin/pytest -q                   # 195 passed
.venv/bin/python scripts/build_spec.py   # SPEC.md unchanged
scripts/start.sh --background --port 8742 && curl -s localhost:8742/api/options | head -c 120 && scripts/stop.sh
.venv/bin/casper write --author bill --source developer --target management --structure status_update \
  --modality slack -i examples/edge-migration-status.md --seed 1 | diff - examples/outputs/status-slack.txt
```

## 11. Known limits (stated, not hidden)

- One author profile (four articles); voice scoring cannot tell same-house-style writers apart (ADR 0007).
- Short drafts get low-confidence voice scores; ranking has little signal on Slack-length text.
- Fact kinds are heuristic (headings, keys, keyword cues); a misfiled fact is still truthful but may sit in the wrong section.
- The built-in writer is formulaic: it restates facts with light rewrites. Source personas only affect emphasis and the closing line. Overlays affect scoring, not wording.
- The live Claude (`claude`) and Antigravity (`agy`) CLI paths should be verified against real CLI sessions once wired; automated tests exercise them through the stand-in fake CLI.
- Web styling uses local CSS tokens in `theme.css`; no sign-in; localhost only.
- Ensure private author email addresses are never committed to git history from the outset (enforced by ADR 0005).
- No accessibility audit yet; Mermaid diagrams have not been browser-rendered.

## 12. Architecture review: what to look at before going further

Ordered by how much each affects what we build next. Each item says what is planned/built, the evidence, and the options. Nothing here has been changed; these are for decision before the next phase.

### 12.1 The voice is measured much more than it is produced

**Built:** a thorough measurement of an author's style (32 scored features, calibrated), and a writer whose only voice levers are contraction forms, a transition word, and a semicolon join, chosen by ranking against that measurement.

**Evidence:** the five saved example drafts, each written for Bill's profile, score 31 to 35 of 100 against it (all "different voice"; the article, the longest, scores 34.6), against 74 to 87 for his own held-out articles. A deliberately casual draft scores 25, so the generated drafts are only a little closer than a text written to be wrong. Part of this is the input (terse status notes are not blog prose) and part is that the writer has little room to move; on short drafts the ranking has almost nothing to choose between.

**Why it matters:** the product promise is "in the voice of". Today the voice affects wording lightly, and the facts dominate. The scorer is good; the generator does not yet use most of what the scorer knows.

**Options:** (a) widen the rewrite space the ranker can use (sentence splitting and merging, active and passive, hedges and intensifiers from the author's lexicon, openers drawn from the author's own exemplars), all still validated; (b) let the Claude or Antigravity (`agy`) CLI writer carry voice and keep the rule-based writer as the guaranteed-faithful baseline; (c) accept that voice is mainly a check on human edits, not a generator, and reposition the product around fidelity and audience adaptation. These lead to different next phases.

### 12.2 Fact classification is heuristic and one of its errors has a visible effect

**Built:** kind comes from explicit key, then heading, then keyword cues, then a default.

**Evidence:** `ingest(notes="The team will review the plan. ...")` files "The team will review the plan." as an **ask**, because "review" is in the ask cue list. An ask makes the writer append a closing line such as "Please let me know if you approve." The notes asked for nothing. "The release is done and we are blocked on legal." becomes a risk, though half of it is progress.

**Why it matters:** the closing line is the one sentence with no fact behind it, and its presence depends entirely on this guess. A wrong guess can put a request in the author's mouth.

**Options:** tighten the cues (drop "review", require a second-person or modal request); make closing lines depend on an explicit ask only (heading or key), not a cue; add a per-fact override file or inline marker (`[risk]`); show the classification in the page so a person can correct it before writing. The last has the best payoff and is not built.

### 12.3 Two writers, two strengths of guarantee

**Built:** the rule-based writer is held to a strict word check (every word from the cited facts, plus a small allow-list). The Claude and Antigravity (`agy`) CLI writers are held to citations, numbers and capitalized names; rewording is a warning.

**Evidence:** [ADR 0009](../docs/adr/0009-fact-traceability-and-ranked-realization.md) says "every sentence cites facts" as one guarantee; the code enforces two different levels. Until exercised against live Claude (`claude`) and Antigravity (`agy`) CLIs, their parsing and prompt handling are validated only against the stand-in fake CLI.

**Why it matters:** a name-and-number check does not catch a changed meaning ("approved" becomes "rejected", "slipped" becomes "ahead"). That gap is acceptable for a draft a person reads, and should be a stated decision, not an accident.

**Options:** accept and document (current); add a conservative content check for the Claude / Antigravity (`agy`) CLI paths (cited fact words must still appear, negations must match); or let the model only rephrase one sentence at a time with the original fact attached, which is easier to verify. Before relying on either CLI backend, run it once against the real `claude` and `agy` binaries.

### 12.4 A hidden coupling between the writer and the validator

**Built:** the strict validator allows words that the writer's rewrite rules may add. The allow-list (`validator._allowed_extra`) is built by importing the writer's tables.

**Evidence:** a new rewrite rule that adds a word fails validation until someone also edits the allow-list. The coupling is real but implicit, and it is the kind of thing that breaks quietly during the "richer rewrites" work in 12.1.

**Options:** make each rewrite rule declare the words it may add (in the same table), and have the validator read only that declaration; or emit the allowed words in the `Draft` so the validator checks what the writer says it did. Cheap to do now; harder after more rules exist.

### 12.5 Voice scoring cannot yet say "this is Bill"

**Built:** a profile-relative score ([ADR 0006](../docs/adr/0006-voice-conformance-scoring.md), accepted) with weights, floors and bands tuned on four articles by one author.

> *[Note: The final screenshot (`Scan_20261120_142218.jpg`) ended at this line; any remaining paragraphs of Section 12.5 or subsequent items were not present in `raw_inputs/`.]*
