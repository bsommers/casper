# Architecture Decision Records (ADRs)

ADRs are append-only and verified for index parity by `tests/smoke/test_adr.py` (`TC-003`).

| ADR | Title | Status | Enforced By |
|---|---|---|---|
| [0001](0001-no-in-process-llm.md) | No In-Process LLM or Hugging Face; Deterministic Rule-Based Realization Default | accepted | `tests/security/test_constraints.py` |
| [0002](0002-one-yaml-per-author.md) | Author Profiles Stored as One YAML File per Author in authors/ | accepted | `tests/unit/test_profile.py` |
| [0003](0003-deterministic-root-spec.md) | Root SPEC.md Deterministically Generated from spec/0[0-9]-*.md | accepted | `tests/smoke/test_spec.py` |
| [0004](0004-gitignore-input-output.md) | input/ and output/ Git-Ignored with README.md Placeholders | accepted | `.gitignore` and `tests/smoke/test_hygiene.py` |
| [0005](0005-three-layer-author-profiles.md) | Three-Layer Author Profiles with Mode 0600 Local Layer and Tamper Guard | accepted | `tests/unit/test_layers.py`, `tests/security/test_privacy.py` |
| [0006](0006-profile-relative-voice-score.md) | Profile-Relative Deterministic 32-Feature Voice Conformance Score | accepted | `tests/unit/test_conformance.py` |
| [0007](0007-catalog-relative-voice-scoring.md) | Catalog-Relative Voice Scoring Deferred Until >=3 Distinct Authors | proposed | Deferred until catalog has >=3 distinct authors in `authors/` |
| [0008](0008-v1-library-scope.md) | v1 Library Scope: 10 Personas, 3 Structures, 5 Modalities, 1 Default Glossary | accepted | `tests/unit/test_libraries.py` |
| [0009](0009-fact-cited-candidates.md) | Every Non-Frame Sentence Cites Facts; Candidate Variants Ranked by Voice Score | accepted | `tests/unit/test_realizer.py`, `tests/unit/test_validator.py` |
| [0010](0010-optional-cli-writers.md) | Optional Claude and Antigravity CLI Writers Behind Explicit Opt-In and Fallback | accepted | `tests/integration/test_llm.py` |
| [0011](0011-localhost-stdlib-web-ui.md) | Localhost-Only Python Stdlib ThreadingHTTPServer and Frameworkless Static UI | accepted | `tests/security/test_web_security.py`, `tests/system/test_web_e2e.py` |
| [0012](0012-shared-rewrites-fidelity-brand.md) | Shared rewrites.py Registry, Tightened Ask Cues, Dual FidelityMode & Ghost Brand Kit | accepted | `tests/unit/test_facts.py`, `tests/unit/test_realizer.py`, `tests/unit/test_validator.py`, `tests/smoke/test_brand.py` |
