"""Unit tests for linguistic feature extraction and author profile builder (TC-007, TC-021, TC-038)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from casper.errors import (
    InputError,
    ProfileError,
    ProfileNotFoundError,
    ProfileTamperedError,
)
from casper.features import (
    DIMENSION_WEIGHTS,
    FEATURE_SPEC_BY_KEY,
    FEATURE_SPECS,
    STABILITY_KEYS,
    analyze,
    compute_stability,
    extract_path,
    extract_stability_vector,
)
from casper.features.lexical import count_syllables
from casper.libraries import load_libraries
from casper.models import Block, BlockKind, Document
from casper.profile import (
    STYLE_GUIDE_AREAS,
    build_profile,
    check_profile_writable,
    compute_body_sha256,
    load_profile,
    render_style_guide,
    save_profile,
)

_EXPECTED_STABILITY_KEYS: tuple[str, ...] = (
    "mean_sentence_length",
    "short_sentence_rate",
    "long_sentence_rate",
    "sentence_length_cv",
    "passive_rate",
    "commas_per_sentence",
    "subordinate_clauses_per_sentence",
    "fragment_rate",
    "question_rate",
    "exclamation_rate",
    "conjunction_start_rate",
    "pronoun_start_rate",
    "transition_start_rate",
    "sentences_per_paragraph",
    "single_sentence_paragraph_rate",
    "flesch_kincaid_grade",
    "mean_word_length",
    "long_word_rate",
    "acronyms_per_1k",
    "first_person_singular_per_1k",
    "first_person_plural_per_1k",
    "second_person_per_1k",
    "contractions_per_1k",
    "em_dashes_per_1k",
    "colons_per_1k",
    "semicolons_per_1k",
    "parentheses_per_1k",
    "commas_per_1k",
    "transitions_per_1k",
    "intensifiers_per_1k",
    "hedges_per_1k",
    "contrast_frames_per_1k",
)


def _make_sample_markdown(idx: int, author: str = "Bill") -> str:
    return f"""---
title: "Edge Migration Note {idx}"
author: "{author}"
---

## Measuring edge reliability

In practice, we keep the rollout narrow before expanding traffic across regions. It isn't magic; it is disciplined engineering. Because the latency budget is tight, our team monitors Service Level Objective (SLO) charts closely, and we test every fallback path.

However, we don't rely on guesswork — we run benchmarks with clear baselines (especially during peak traffic). The system was tested by operators across staging, canary, and production! Really, can you ship safely without measuring error budgets?

## Operating at the edge

In practice, teams need simple contracts: clean schemas, deterministic builds, and fast rollbacks. The result is predictable delivery at the edge. The result is fewer incidents when you need to ship quickly. Nothing is invented.

- **Clear ownership:** Every milestone names one owner who tracks blockers when you need to escalate.
- **Fast rollback:** Keep the rollback path automated; we verify it weekly rather than hoping it works.

Not a guess, but a measurement guides our next release. Perhaps the schedule could shift slightly, yet our core milestone remains firm. Measure the change before expanding scope?
"""


def _write_n_word_doc(path: Path, n_words: int, author: str = "Bill") -> Path:
    if n_words == 0:
        content = f"---\ntitle: Empty\nauthor: {author}\n---\n"
    else:
        # Build clean sentences of 10 words each so spaCy splits cleanly
        base_sentence = "The team ships clean code when tests pass every day."
        words_pool: list[str] = []
        while len(words_pool) < n_words:
            words_pool.extend(base_sentence.split())
        trimmed = words_pool[:n_words]
        # Ensure terminal punctuation
        if not trimmed[-1].endswith("."):
            trimmed[-1] = trimmed[-1].rstrip(".") + "."
        body = " ".join(trimmed)
        content = f"---\ntitle: Doc {n_words}\nauthor: {author}\n---\n\n{body}\n"
    path.write_text(content, encoding="utf-8")
    return path


def test_stability_keys_exact_order_and_metadata() -> None:
    assert len(STABILITY_KEYS) == 32
    assert STABILITY_KEYS == _EXPECTED_STABILITY_KEYS
    assert len(FEATURE_SPECS) == 32
    assert set(FEATURE_SPEC_BY_KEY) == set(STABILITY_KEYS)
    for spec in FEATURE_SPECS:
        assert spec.dimension in DIMENSION_WEIGHTS
        assert spec.weight > 0
        assert spec.floor > 0
        assert "." in spec.profile_path


def test_tc007_build_profile_four_sample_docs(tmp_path: Path) -> None:
    """TC-007: build_profile on 4 synthetic docs >=150 words produces full v1 schema."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    for i in range(1, 5):
        author = "William" if i == 4 else "Bill"
        (corpus_dir / f"doc{i}.md").write_text(
            _make_sample_markdown(i, author=author), encoding="utf-8"
        )

    profile = build_profile(
        "bill",
        "Bill",
        [corpus_dir],
        aliases=["William"],
        strict_authors=True,
        min_words=150,
    )

    assert profile["schema_version"] == 1
    assert profile["author"] == {"id": "bill", "display_name": "Bill", "aliases": ["William"]}
    assert "email" not in profile["author"]
    assert "consent" not in profile["author"]

    gen = profile["generated"]
    assert gen["tool"] == "casper"
    assert gen["spacy_model"] == "en_core_web_sm"
    assert len(gen["corpus_sha256"]) == 64
    assert len(gen["body_sha256"]) == 64
    assert gen["body_sha256"] == compute_body_sha256(profile)

    assert profile["corpus"]["document_count"] == 4
    assert profile["corpus"]["total_words"] >= 600
    assert profile["corpus"]["total_words"] == profile["lexical"]["words"]

    # Style guide: exactly 8 rules, id == area
    sg = profile["style_guide"]
    assert len(sg) == 8
    assert tuple(item["id"] for item in sg) == STYLE_GUIDE_AREAS
    assert all(item["id"] == item["area"] and len(item["rule"]) > 10 for item in sg)

    # All 11 feature groups + stability present
    for key in (
        "sentences",
        "paragraphs",
        "lexical",
        "voice",
        "typography",
        "headings",
        "lists",
        "structure",
        "function_word_per_1k",
        "signature",
        "exemplars",
        "stability",
    ):
        assert key in profile

    # 60 function words exact match
    expected_fw = load_libraries().lexicons["function_words"]
    assert len(expected_fw) == 60
    assert list(profile["function_word_per_1k"].keys()) == list(expected_fw)

    # 32 stability keys with {min, max, stdev}
    stab = profile["stability"]
    assert tuple(stab.keys()) == STABILITY_KEYS
    for key in STABILITY_KEYS:
        assert set(stab[key].keys()) == {"min", "max", "stdev"}
        assert stab[key]["min"] <= stab[key]["max"]
        assert stab[key]["stdev"] >= 0.0

    # Signature & exemplars limits and content
    sig = profile["signature"]
    assert 1 <= len(sig["recurring_phrases"]) <= 12
    assert len(sig["bounded_phrases"]) <= 12
    assert len(sig["sentence_frames"]) <= 8
    assert any("in practice" in p or "at the edge" in p for p in sig["recurring_phrases"])

    ex = profile["exemplars"]
    assert 1 <= len(ex["openers"]) <= 4
    assert 1 <= len(ex["closers"]) <= 4
    assert 1 <= len(ex["short_lines"]) <= 4
    for sl in ex["short_lines"]:
        assert len(sl.split()) <= 8

    # Voice rhetoric, contractions, punctuation, lists, headings detected
    assert profile["voice"]["contractions_per_1k"] > 0
    assert profile["voice"]["rhetoric"]["contrast_frames_per_1k"] > 0
    assert profile["voice"]["rhetoric"]["acronym_introductions"] >= 4
    assert profile["lists"]["item_count"] == 8
    assert profile["lists"]["emphasis_lead_rate"] == 1.0
    assert profile["headings"]["count"] == 8
    assert profile["headings"]["case_style"] == "sentence"
    assert len(profile["sources"]) == 4
    assert all(src["byline_matches_author"] is True for src in profile["sources"])


def test_tc021_word_count_boundaries_and_filtering(tmp_path: Path) -> None:
    """TC-021: docs with 0 and 149 words dropped; 150 and 151 retained; all-dropped raises InputError."""
    f0 = _write_n_word_doc(tmp_path / "w0.md", 0)
    f149 = _write_n_word_doc(tmp_path / "w149.md", 149)
    f150 = _write_n_word_doc(tmp_path / "w150.md", 150)
    f151 = _write_n_word_doc(tmp_path / "w151.md", 151)

    profile = build_profile("bill", "Bill", [f0, f149, f150, f151], min_words=150)
    assert profile["corpus"]["document_count"] == 2
    assert profile["corpus"]["total_words"] == 301
    retained_words = sorted(s["prose_words"] for s in profile["sources"])
    assert retained_words == [150, 151]

    # All dropped raises InputError
    with pytest.raises(InputError, match="No eligible documents"):
        build_profile("bill", "Bill", [f0, f149], min_words=150)

    # strict_authors filters non-matching author
    f_other = _write_n_word_doc(tmp_path / "other.md", 160, author="Someone Else")
    with pytest.raises(InputError, match="No eligible documents"):
        build_profile("bill", "Bill", [f_other], strict_authors=True, min_words=150)

    # Validation errors on empty args / empty dir
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(InputError):
        build_profile("", "Bill", [f150])
    with pytest.raises(InputError):
        build_profile("bill", "  ", [f150])
    with pytest.raises(InputError):
        build_profile("bill", "Bill", [empty_dir])


def test_excluded_voice_blocks_and_summary_rate() -> None:
    """SUMMARY/AUDIENCE/RESOURCES excluded from prose counts & voice; SUMMARY drives has_summary_rate."""
    doc_with_summary = Document(
        source="a.html",
        format="html",
        title="Doc A",
        sha256="a" * 64,
        blocks=(
            Block(BlockKind.HEADING, "Title Case Heading", level=2),
            Block(BlockKind.SUMMARY, "TLDR: I hate exclamation marks!!! Very really totally!!!"),
            Block(BlockKind.AUDIENCE, "Prerequisites: I assume you know everything."),
            Block(BlockKind.RESOURCES, "Further reading: see links here.", links=10),
            Block(
                BlockKind.PARAGRAPH,
                "We build reliable software. We verify every release carefully.",
                links=1,
            ),
        ),
    )
    doc_without_summary = Document(
        source="b.html",
        format="html",
        title="Doc B",
        sha256="b" * 64,
        blocks=(
            Block(BlockKind.HEADING, "ALL CAPS HEADING", level=2),
            Block(
                BlockKind.PARAGRAPH,
                "We ship predictable systems. In summary, testing keeps quality high.",
            ),
        ),
    )

    feats = analyze([doc_with_summary, doc_without_summary])
    assert feats["lexical"]["words"] == 19
    assert feats["voice"]["person_per_1k"]["first_singular"] == 0.0
    assert feats["sentences"]["exclamation_rate"] == 0.0
    assert feats["voice"]["lexicon_per_1k"]["intensifiers"] == 0.0
    assert feats["structure"]["has_summary_rate"] == 0.5
    assert "summary" in feats["structure"]["closing_patterns"]
    assert feats["headings"]["case_style"] == "mixed"
    assert feats["headings"]["case_shares"] == {"sentence": 0.0, "title": 0.5, "upper": 0.5}


def test_feature_edge_cases_quotes_empty_and_single_doc() -> None:
    """Cover quote styles, empty docs, single-doc stability, fragments, and syllable edge cases."""
    assert count_syllables("") == 1
    assert count_syllables("the") == 1
    assert count_syllables("reliable") >= 3
    assert count_syllables("make") == 1

    # Empty corpus
    empty_feats = analyze([])
    assert empty_feats["sentences"]["count"] == 0
    assert empty_feats["paragraphs"]["count"] == 0
    assert empty_feats["lexical"]["words"] == 0
    assert empty_feats["headings"]["case_style"] == "none"
    assert empty_feats["lists"]["item_count"] == 0
    assert empty_feats["structure"]["mean_doc_words"] == 0.0
    assert empty_feats["typography"]["quote_style"] == "none"
    assert len(empty_feats["stability"]) == 32
    assert extract_path(empty_feats, "missing.path") == 0.0
    assert compute_stability([])["mean_sentence_length"] == {"min": 0.0, "max": 0.0, "stdev": 0.0}

    # Single doc with curly quotes, mixed quotes, fragments, non-oxford comma, reflection closer
    curly_doc = Document(
        source="curly.txt",
        format="text",
        sha256="c" * 64,
        blocks=(
            Block(BlockKind.HEADING, "Overview", level=2),
            Block(BlockKind.HEADING, "12345", level=2),
            Block(
                BlockKind.PARAGRAPH,
                "\u201cReliability matters.\u201d No doubt. We packed apples, pears and plums.",
            ),
        ),
    )
    f_curly = analyze([curly_doc])
    assert f_curly["typography"]["quote_style"] == "curly"
    assert f_curly["voice"]["oxford_comma_rate"] == 0.0
    assert f_curly["sentences"]["fragment_rate"] > 0.0
    assert "reflection" in f_curly["structure"]["closing_patterns"]
    # Single-doc stability: min == max == val, stdev == 0.0
    vec = extract_stability_vector(f_curly)
    for k in STABILITY_KEYS:
        assert f_curly["stability"][k]["stdev"] == 0.0
        assert f_curly["stability"][k]["min"] == pytest.approx(round(vec[k], 4))
        assert f_curly["stability"][k]["max"] == pytest.approx(round(vec[k], 4))

    # Mixed quote style
    mixed_doc = Document(
        source="mixed.txt",
        format="text",
        sha256="d" * 64,
        blocks=(Block(BlockKind.PARAGRAPH, 'He said "yes" and \u201cno\u201d.'),),
    )
    assert analyze([mixed_doc])["typography"]["quote_style"] == "mixed"

    # Single-quote-only straight fallback
    sq_doc = Document(
        source="sq.txt",
        format="text",
        sha256="e" * 64,
        blocks=(Block(BlockKind.PARAGRAPH, "It's working fine."),),
    )
    assert analyze([sq_doc])["typography"]["quote_style"] == "straight"

    # Non-alpha heading only
    num_head_doc = Document(
        source="nh.txt",
        format="text",
        sha256="f" * 64,
        blocks=(
            Block(BlockKind.HEADING, "2026", level=2),
            Block(BlockKind.PARAGRAPH, "A short sentence."),
        ),
    )
    assert analyze([num_head_doc])["headings"]["case_style"] == "none"

    # Style guide deterministic on empty features
    sg = render_style_guide(empty_feats)
    assert len(sg) == 8


def test_tc038_save_load_tamper_legacy_and_idempotency(tmp_path: Path) -> None:
    """TC-038: atomic save_profile, tamper guard, --force .bak, legacy overwrite, error handling."""
    f150 = _write_n_word_doc(tmp_path / "sample.md", 160)
    profile = build_profile("bill", "Bill", [f150], min_words=150)

    out_path = tmp_path / "authors" / "bill.yaml"
    # Save when body_sha256 is missing -> save_profile computes it
    profile_no_hash = {**profile, "generated": {**profile["generated"], "body_sha256": ""}}
    saved = save_profile(out_path, profile_no_hash)
    assert saved == out_path
    assert out_path.is_file()
    # Zero lingering .tmp.* files
    assert [p for p in out_path.parent.iterdir() if ".tmp." in p.name] == []

    # Round-trip load and verify body_sha256 matches
    loaded = load_profile(out_path)
    assert loaded["generated"]["body_sha256"] == compute_body_sha256(loaded)

    # Idempotent overwrite without force when untampered
    check_profile_writable(out_path, force=False)
    save_profile(out_path, profile, force=False)
    assert not Path(f"{out_path}.bak").exists()

    # Hand-edit (tamper) the YAML without updating body_sha256
    tampered_text = out_path.read_text(encoding="utf-8").replace(
        "display_name: Bill", "display_name: HandEdited"
    )
    out_path.write_text(tampered_text, encoding="utf-8")

    with pytest.raises(ProfileTamperedError) as exc_info:
        check_profile_writable(out_path, force=False)
    assert exc_info.value.exit_code == 3

    with pytest.raises(ProfileTamperedError):
        save_profile(out_path, profile, force=False)

    # With force=True, copies tampered file to <path>.bak and replaces atomically
    save_profile(out_path, profile, force=True)
    bak_path = Path(f"{out_path}.bak")
    assert bak_path.is_file()
    assert "HandEdited" in bak_path.read_text(encoding="utf-8")
    reloaded = load_profile(out_path)
    assert reloaded["author"]["display_name"] == "Bill"
    assert reloaded["generated"]["body_sha256"] == compute_body_sha256(reloaded)

    # Legacy file lacking body_sha256 is overwritable without force
    legacy_path = tmp_path / "authors" / "legacy.yaml"
    legacy_path.write_text(
        yaml.safe_dump({"schema_version": 1, "author": {"id": "legacy"}, "generated": {}}),
        encoding="utf-8",
    )
    check_profile_writable(legacy_path, force=False)
    save_profile(legacy_path, profile, force=False)
    assert load_profile(legacy_path)["author"]["id"] == "bill"

    # Missing file -> ProfileNotFoundError
    with pytest.raises(ProfileNotFoundError):
        load_profile(tmp_path / "authors" / "missing.yaml")

    # Corrupt YAML -> ProfileError
    corrupt_path = tmp_path / "authors" / "corrupt.yaml"
    corrupt_path.write_text(":::invalid: [yaml", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(corrupt_path)

    # Non-mapping YAML -> ProfileError
    list_path = tmp_path / "authors" / "list.yaml"
    list_path.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profile(list_path)

    # Verify PID temp file is absent
    assert not out_path.with_name(f"{out_path.name}.tmp.{os.getpid()}").exists()
