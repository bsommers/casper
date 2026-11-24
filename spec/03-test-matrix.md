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
