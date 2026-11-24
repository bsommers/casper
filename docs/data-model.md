# Data Model & Shipped Libraries

Reference for Casper's core types in [`src/casper/models.py`](../src/casper/models.py), author profile YAML schema in [`src/casper/profile.py`](../src/casper/profile.py) and [`src/casper/layers.py`](../src/casper/layers.py), and shipped YAML libraries under [`src/casper/data/`](../src/casper/data).

## Core Enumerations

| Enum | Values |
|---|---|
| `BlockKind` | `title`, `heading`, `paragraph`, `list_item`, `quote`, `code`, `summary`, `audience`, `resources` (`EXCLUDED_VOICE_BLOCK_KINDS` excludes `summary`, `audience`, `resources`) |
| `FactKind` | `status`, `progress`, `risk`, `next_step`, `decision`, `background`, `detail`, `metric`, `ask` |
| `PersonaKind` | `source`, `target` |
| `DepthLevel` | `low` (cap `1`), `medium` (cap `3`), `high` (cap `6`) |
| `JargonLevel` | `low`, `medium`, `high` |
| `MarkupKind` | `markdown`, `slack`, `html`, `plain` |
| `BackendKind` | `rules`, `claude`, `agy` |
| `FidelityMode` | `strict`, `assisted` |
| `CheckLevel` | `error`, `warning` |
| `MatchBand` | `strong`, `close`, `partial`, `different` |
| `ConfidenceBand` | `high`, `medium`, `low` |

## Core Dataclasses

- **`Block`**: `kind`, `text`, `level`, `links`, `emphasis_lead`
- **`Document`**: `source`, `format`, `title`, `authors`, `published`, `modified`, `canonical_url`, `description`, `blocks`, `sha256`, `notes`
- **`Fact`**: `id`, `kind` (`FactKind`), `text`, `source`, `order`, `entities`, `metrics`, `dates`, `owners`, `salience`, `classification_source`
- **`FactModel`**: `facts`, `graph` (NetworkX relation graph), `input_hashes`, `digest`, `warnings`
- **`Persona`**: `id`, `kind`, `priorities`, `vocabulary_include`, `vocabulary_avoid`, `detail_depth`, `jargon_level`, `framing_patterns`, `typical_concerns`, `cta_styles`, `section_priority`
- **`Section` & `Structure`**: `Structure` (`id`, `goal`, `sections`, `compatible_modalities`, `default_target_personas`) contains `Section` entries (`name`, `purpose`, `fact_kinds`, `required`, `min_words`, `max_words`, `heading`)
- **`Modality`**: `id`, `markup`, `max_words`, `max_chars`, `title`, `headings` (`none`, `h2`, `bold`, `slack_bold`), `bullets`, `description`
- **`Glossary`**: `plain` (jargon simplifications), `preferred` (wording substitutions), `banned` (disallowed terms)
- **`Libraries`**: `personas`, `structures`, `modalities`, `glossary`, `phrasebank`, `lexicons`, `digest`
- **`Plan` & `PlanSection`**: `Plan` (`structure`, `sections`, `unused_facts`, `warnings`) groups `Fact`s into `PlanSection`s
- **`AdaptedPlan`**: `structure`, `source`, `target`, `sections`, `substitutions`, `cta_style`, `warnings`
- **`Draft`, `DraftSection`, & `Sentence`**: `Draft` (`sections`, `title`, `warnings`, `candidates_considered`, `backend`, `declared_additions`, `meta`) holds `DraftSection`s of `Sentence`s (`text`, `fact_ids`, `frame`)
- **`Validation` & `CheckFinding`**: `Validation` (`ok`, `findings`, `persona_score`, `voice_report`, `fidelity_mode`)
- **`ConformanceReport`**, **`FeatureScore`**, & **`GapItem`**: `ConformanceReport` (`overall`, `band`, `confidence`, `word_count`, `dimensions`, `features`, `largest_gaps`, `signature_matches`, `frame_matches`)
- **`ReproducibilityRecord`** & **`BackendRecord`**: `ReproducibilityRecord` (`tool_version`, `seed`, `candidates`, `selectors`, `input_hashes`, `facts_digest`, `config_digest`, `author_corpus_sha256`, `output_sha256`, `backend`, `record_sha256`)
- **`Brief`**: `structure`, `modality`, `source`, `target`, `author`, `inputs`, `notes`, `topic`, `seed`, `candidates`, `min_voice`, `banned`, `fact_overrides`, `project_dir`, `authors_dir`, `backend`, `fallback`, `timeout`, `model`
- **`Result`**: `text`, `draft`, `validation`, `fact_trace`, `record`, `facts`

Additional command summary dataclasses: `DriftIssue`, `DriftReport`, `AuthorSummary`, `AuthorDiff`, `BackendAvailability`, `BackendStatusReport`.

## Author Profile YAML Schema

Generated profiles (`schema_version: 1`) contain metadata (`author`, `generated`, `corpus`, `sources`), an 8-rule `style_guide` (`sentences`, `paragraphs`, `lexical`, `voice`, `punctuation`, `rhetoric`, `headings`, `structure`), and **11 extracted feature groups** plus **32-key cross-document `stability`**:

1. `sentences`
2. `paragraphs`
3. `lexical`
4. `voice`
5. `typography`
6. `headings`
7. `lists`
8. `structure`
9. `function_word_per_1k`
10. `signature`
11. `exemplars`

### The 32 `STABILITY_KEYS`

Defined in [`src/casper/features/stability.py`](../src/casper/features/stability.py) across 7 scored dimensions (`rhythm`, `openers`, `paragraphs`, `register`, `point_of_view`, `punctuation`, `rhetoric`; `DIMENSION_WEIGHTS` also includes `function_words` and `structure`):

- **rhythm (10):** `mean_sentence_length`, `short_sentence_rate`, `long_sentence_rate`, `sentence_length_cv`, `passive_rate`, `commas_per_sentence`, `subordinate_clauses_per_sentence`, `fragment_rate`, `question_rate`, `exclamation_rate`
- **openers (3):** `conjunction_start_rate`, `pronoun_start_rate`, `transition_start_rate`
- **paragraphs (2):** `sentences_per_paragraph`, `single_sentence_paragraph_rate`
- **register (4):** `flesch_kincaid_grade`, `mean_word_length`, `long_word_rate`, `acronyms_per_1k`
- **point_of_view (4):** `first_person_singular_per_1k`, `first_person_plural_per_1k`, `second_person_per_1k`, `contractions_per_1k`
- **punctuation (5):** `em_dashes_per_1k`, `colons_per_1k`, `semicolons_per_1k`, `parentheses_per_1k`, `commas_per_1k`
- **rhetoric (4):** `transitions_per_1k`, `intensifiers_per_1k`, `hedges_per_1k`, `contrast_frames_per_1k`

### Integrity Guard & 3-Layer Merge Algebra

- **`generated.body_sha256` Tamper Guard:** Canonical SHA-256 of the profile JSON payload (`sort_keys=True`, excluding `generated.body_sha256`). Any manual edit to `<id>.yaml` causes `check_profile_writable()` to raise `ProfileTamperedError` on rebuild unless `--force` is given (which saves `<id>.yaml.bak`).
- **Resolution Precedence:** `generated` -> `curated` -> `local` -> `curated.overlays.<name>` -> `local.overlays.<name>`.
- **List Directives:** Plain list assignments in higher layers raise `ProfileError`. Lists must be modified using `$add`, `$remove`, or `$replace` mappings (`$replace` supersedes `$add`/`$remove`).
- **`style_guide` Edits:** Must be an `id`-keyed mapping where each value is `"$remove"`, a replacement rule string, or `{"area": ..., "rule": ...}`.

## Shipped YAML Libraries (`src/casper/data/`)

All libraries can be extended or overridden per project via `--project-dir` (`project_dir` in `Brief`).

- **10 Personas (`personas/`):**
  - Source (5): `analyst`, `developer`, `product_owner`, `project_manager`, `tech_lead`
  - Target (5): `customer`, `engineering`, `executive`, `management`, `product_owner`
- **3 Structures (`structures/`) & 11 Valid `structure × modality` Combinations:**
  - `status_update` × `{slack, email, memo, plain}` (4)
  - `decision_memo` × `{memo, email, article, plain}` (4)
  - `technical_article` × `{article, memo, plain}` (3)
- **5 Modalities (`modalities/`):**
  - `slack` (`slack`, 180w / 1,200c), `email` (`markdown`, 350w / 2,500c), `memo` (`markdown`, 800w / 6,000c), `article` (`html`, 2,500w / 20,000c), `plain` (`plain`, 200w / 1,400c)
- **Default Glossary (`glossaries/default.yaml`):** 10 `plain` jargon mappings, 6 `preferred` substitutions, 5 `banned` buzzwords.
- **Phrasebank (`phrasebank.yaml`):** 7 CTA categories (`approval`, `alignment`, `decision`, `direct`, `feedback`, `next_step`, `technical_review`).
- **Lexicons (`lexicons.yaml`):** `transitions` (19), `intensifiers` (12), `hedges` (18), `negations` (25), and `function_words` (60).
