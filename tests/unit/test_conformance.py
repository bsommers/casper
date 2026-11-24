"""Unit tests for voice conformance scoring (TC-009, TC-022)."""

from __future__ import annotations

import copy
import math
from typing import Any

import pytest

from casper.conformance import SCALAR_DIMENSIONS, _band_for_score, score
from casper.errors import InputError
from casper.features import FEATURE_SPEC_BY_KEY, STABILITY_KEYS, analyze
from casper.models import Block, BlockKind, ConfidenceBand, Document, MatchBand
from casper.parsing import load_nlp


@pytest.fixture(scope="module")
def nlp() -> Any:
    return load_nlp(ner=False)


def _doc_from_paragraphs(
    paragraphs: list[str],
    *,
    headings: list[str] | None = None,
    source: str = "<test>",
) -> Document:
    blocks: list[Block] = []
    heading_list = headings or []
    for idx, para in enumerate(paragraphs):
        if idx < len(heading_list):
            blocks.append(Block(kind=BlockKind.HEADING, text=heading_list[idx], level=2))
        blocks.append(Block(kind=BlockKind.PARAGRAPH, text=para))
    for extra_heading in heading_list[len(paragraphs) :]:
        blocks.append(Block(kind=BlockKind.HEADING, text=extra_heading, level=2))
    return Document(source=source, format="markdown", blocks=tuple(blocks))


def _author_corpus_docs() -> list[Document]:
    doc1 = _doc_from_paragraphs(
        [
            "We build reliable services with small, focused teams. In practice, every release "
            "starts with a clear baseline. When you need to ship fast, keep the change tight.",
            "The result is predictable behavior under load. We measure latency first, then we "
            "cut unnecessary work. It isn't magic; it's discipline.",
            "Start with the constraint that matters most. Measure the change before expanding "
            "scope. You can't fix what you don't observe.",
        ],
        headings=["Why baselines matter", "Measuring latency early", "Keeping changes small"],
        source="doc1.md",
    )
    doc2 = _doc_from_paragraphs(
        [
            "We design clear interfaces for durable systems. In practice, simple contracts beat "
            "clever abstractions. When you need to debug an outage, clarity saves hours.",
            "The result is lower variance across deployments. We test every boundary before we "
            "ship to production. We don't guess when metrics tell the story.",
            "Keep each pull request easy to read. Check the baseline after each rollout. You "
            "won't regret investing in repeatable checks.",
        ],
        headings=["Designing clear contracts", "Testing system boundaries"],
        source="doc2.md",
    )
    doc3 = _doc_from_paragraphs(
        [
            "We run deterministic pipelines across our stack. In practice, repeatable builds "
            "prevent silent drift. When you need to trace a failure, clean logs matter.",
            "The result is faster recovery during incidents. We verify each step locally before "
            "pushing code. It doesn't slow us down; it keeps quality steady.",
            "Review the edge cases early. Cut complexity whenever a simpler rule works. We can't "
            "afford hidden surprises in production.",
        ],
        headings=["Running deterministic pipelines", "Recovering from incidents"],
        source="doc3.md",
    )
    return [doc1, doc2, doc3]


@pytest.fixture(scope="module")
def author_profile(nlp: Any) -> dict[str, Any]:
    docs = _author_corpus_docs()
    feats = analyze(docs, nlp=nlp)
    total_words = int(feats["lexical"]["words"])
    return {
        "schema_version": 1,
        "author": {"id": "alice", "display_name": "Alice", "aliases": []},
        "corpus": {
            "document_count": len(docs),
            "total_words": total_words,
            "avg_doc_words": round(total_words / len(docs), 2),
        },
        **feats,
    }


def _make_n_word_doc(n_words: int, *, headings: list[str] | None = None) -> Document:
    """Create a Document whose lexical word count is exactly `n_words`."""
    if n_words <= 0:
        return Document(source="<empty>", format="text", blocks=())

    base_sentence = "We test the clear system plan now."  # 7 words
    words_needed = n_words
    sentences: list[str] = []
    while words_needed >= 7:
        sentences.append(base_sentence)
        words_needed -= 7
    if words_needed > 0:
        tail_words = ["We", "check", "the", "new", "plan", "today"][:words_needed]
        sentences.append(" ".join(tail_words) + ".")

    paragraphs: list[str] = []
    chunk_size = 5
    for idx in range(0, len(sentences), chunk_size):
        paragraphs.append(" ".join(sentences[idx : idx + chunk_size]))
    return _doc_from_paragraphs(paragraphs, headings=headings, source=f"<words-{n_words}>")


def test_tc009_matching_vs_contrasting_prose_and_determinism(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """TC-009: Matching prose scores significantly higher than contrasting prose; deterministic."""
    matching_doc = _doc_from_paragraphs(
        [
            "We build focused tools for reliable operations. In practice, clear baselines catch "
            "drift early. When you need to ship safely, keep each change small.",
            "The result is steady performance under pressure. We verify metrics before we expand "
            "rollout. It isn't flashy; it's dependable.",
            "Measure each step carefully. Cut extra layers when a plain rule works. You won't "
            "miss the extra ceremony.",
        ],
        headings=["Building focused tools", "Verifying metrics early"],
        source="matching.md",
    )
    contrasting_doc = _doc_from_paragraphs(
        [
            "NOTWITHSTANDING the extraordinarily multifaceted organizational paradigms "
            "contemporaneously instantiated across heterogeneous bureaucratic infrastructures, "
            "one might conceivably hypothesize—perhaps, somewhat tentatively, albeit with "
            "exceedingly substantial philosophical reservations (and indeed considerable "
            "epistemological hesitation!)—that the hyper-abstracted conceptualization of "
            "enterprise-wide operationalization could arguably be reconfigured; nevertheless, "
            "such monumental transformations are invariably characterized by protracted "
            "deliberations, labyrinthine committee reviews, interminable documentation cycles, "
            "and extraordinarily convoluted methodological justifications that are seldom "
            "comprehended by uninitiated observers?!",
        ],
        source="contrasting.md",
    )

    rep_match_1 = score(author_profile, matching_doc, nlp=nlp)
    rep_match_2 = score(author_profile, matching_doc, nlp=nlp)
    rep_contrast = score(author_profile, contrasting_doc, nlp=nlp)

    assert rep_match_1 == rep_match_2
    assert rep_match_1.to_dict() == rep_match_2.to_dict()

    assert 0.0 <= rep_match_1.overall <= 100.0
    assert 0.0 <= rep_contrast.overall <= 100.0
    assert rep_match_1.overall > rep_contrast.overall + 25.0
    assert rep_match_1.band in {MatchBand.STRONG, MatchBand.CLOSE}
    assert rep_contrast.band in {MatchBand.DIFFERENT, MatchBand.PARTIAL}
    assert len(rep_match_1.features) == len(STABILITY_KEYS) == 32
    assert set(SCALAR_DIMENSIONS).issubset(rep_match_1.dimensions.keys())
    assert "function_words" in rep_match_1.dimensions
    assert "structure" in rep_match_1.dimensions


def test_tc009_pinned_feature_overrides_target_and_stdev(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """TC-009: Pins override author target (and optional stdev) and set FeatureScore.pinned."""
    cand_doc = _make_n_word_doc(140)
    cand_feats = analyze([cand_doc], nlp=nlp)
    cand_msl = float(cand_feats["sentences"]["length_words"]["mean"])

    pinned_profile = copy.deepcopy(author_profile)
    pinned_profile["pins"] = {
        "mean_sentence_length": {"value": 30.0, "stdev": 2.5},
        "short_sentence_rate": {"value": 0.5},
    }

    report = score(pinned_profile, cand_doc, nlp=nlp)
    by_name = {fs.name: fs for fs in report.features}

    msl = by_name["mean_sentence_length"]
    assert msl.pinned is True
    assert msl.author_value == pytest.approx(30.0)
    assert msl.candidate_value == pytest.approx(cand_msl)

    avg_doc_words = float(pinned_profile["corpus"]["avg_doc_words"])
    widen = min(1.5, max(1.0, math.sqrt(avg_doc_words / report.word_count)))
    spec_msl = FEATURE_SPEC_BY_KEY["mean_sentence_length"]
    expected_sigma = max(2.5, spec_msl.floor, 0.1 * abs(30.0)) * widen
    expected_z = abs(cand_msl - 30.0) / expected_sigma
    expected_score = math.exp(-(expected_z**2) / 4.5)
    assert msl.sigma == pytest.approx(expected_sigma)
    assert msl.z == pytest.approx(expected_z)
    assert msl.score == pytest.approx(expected_score)

    # Pin without explicit stdev keeps profile stability stdev
    ssr = by_name["short_sentence_rate"]
    assert ssr.pinned is True
    assert ssr.author_value == pytest.approx(0.5)
    prof_ssr_stdev = float(pinned_profile["stability"]["short_sentence_rate"]["stdev"])
    spec_ssr = FEATURE_SPEC_BY_KEY["short_sentence_rate"]
    expected_ssr_sigma = max(prof_ssr_stdev, spec_ssr.floor, 0.1 * 0.5) * widen
    assert ssr.sigma == pytest.approx(expected_ssr_sigma)

    # Unpinned feature stays pinned=False
    assert by_name["passive_rate"].pinned is False


def test_tc022_word_count_and_confidence_boundaries(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """TC-022: Word count boundaries 0 (InputError), 1/249 (LOW), 250/999 (MEDIUM), 1000 (HIGH)."""
    with pytest.raises(InputError, match="no scorable prose"):
        score(author_profile, _make_n_word_doc(0), nlp=nlp)

    # Excluded voice blocks only -> also unscorable
    excluded_only = Document(
        source="<excluded>",
        format="html",
        blocks=(
            Block(kind=BlockKind.HEADING, text="Summary", level=2),
            Block(kind=BlockKind.SUMMARY, text="This summary block is excluded from voice."),
        ),
    )
    with pytest.raises(InputError, match="no scorable prose"):
        score(author_profile, excluded_only, nlp=nlp)

    boundaries = [
        (1, ConfidenceBand.LOW),
        (249, ConfidenceBand.LOW),
        (250, ConfidenceBand.MEDIUM),
        (999, ConfidenceBand.MEDIUM),
        (1000, ConfidenceBand.HIGH),
    ]
    for count, expected_conf in boundaries:
        doc = _make_n_word_doc(count)
        report = score(author_profile, doc, nlp=nlp)
        assert report.word_count == count
        assert report.confidence == expected_conf


def test_tc022_headings_boundaries_and_exact_structure_math(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """TC-022 & TC-009: Headings 0/1 omit `structure`; >=2 activates exact density + case math."""
    doc_h0 = _make_n_word_doc(200, headings=[])
    doc_h1 = _make_n_word_doc(200, headings=["Single heading"])
    doc_h2 = _make_n_word_doc(
        200,
        headings=["ALL CAPS HEADING", "Title Case Heading Here"],
    )

    rep_h0 = score(author_profile, doc_h0, nlp=nlp)
    rep_h1 = score(author_profile, doc_h1, nlp=nlp)
    rep_h2 = score(author_profile, doc_h2, nlp=nlp)

    assert "structure" not in rep_h0.dimensions
    assert "structure" not in rep_h1.dimensions
    assert "structure" in rep_h2.dimensions

    # Verify exact structure formula from spec/01-data-model.md §5
    cand_feats = analyze([doc_h2], nlp=nlp)
    avg_doc_words = float(author_profile["corpus"]["avg_doc_words"])
    widen = min(1.5, max(1.0, math.sqrt(avg_doc_words / rep_h2.word_count)))

    prof_density = float(author_profile["headings"]["density_per_1k"])
    cand_density = float(cand_feats["headings"]["density_per_1k"])
    density_sigma = max(1.5, 0.25 * prof_density) * widen
    density_score = math.exp(-((abs(cand_density - prof_density) / density_sigma) ** 2) / 4.5)

    prof_shares = author_profile["headings"]["case_shares"]
    cand_shares = cand_feats["headings"]["case_shares"]
    case_score = 1.0 - 0.5 * sum(
        abs(float(cand_shares[k]) - float(prof_shares[k])) for k in ("sentence", "title", "upper")
    )
    case_score = min(1.0, max(0.0, case_score))
    expected_structure = 0.5 * (density_score + case_score)

    assert rep_h2.dimensions["structure"] == pytest.approx(expected_structure)

    # Profile with 0 headings must NOT include `structure` even if candidate has >=2 headings
    no_heading_profile = copy.deepcopy(author_profile)
    no_heading_profile["headings"]["count"] = 0
    rep_prof_h0 = score(no_heading_profile, doc_h2, nlp=nlp)
    assert "structure" not in rep_prof_h0.dimensions


def test_tc009_largest_gaps_ordering_cap_and_explanations(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """TC-009: largest_gaps has <=6 items, all <0.5, sorted worst-first with higher/lower text."""
    # Craft extreme pins on 10 features to guarantee >6 features score <0.5
    extreme_profile = copy.deepcopy(author_profile)
    extreme_profile["pins"] = {
        "mean_sentence_length": {"value": 80.0, "stdev": 1.0},
        "short_sentence_rate": {"value": 0.99, "stdev": 0.01},
        "long_sentence_rate": {"value": 0.99, "stdev": 0.01},
        "passive_rate": {"value": 0.99, "stdev": 0.01},
        "question_rate": {"value": 0.99, "stdev": 0.01},
        "exclamation_rate": {"value": 0.99, "stdev": 0.01},
        "flesch_kincaid_grade": {"value": 28.0, "stdev": 0.5},
        "em_dashes_per_1k": {"value": 100.0, "stdev": 1.0},
        "colons_per_1k": {"value": 100.0, "stdev": 1.0},
        "semicolons_per_1k": {"value": 100.0, "stdev": 1.0},
    }

    cand_doc = _make_n_word_doc(200)
    report = score(extreme_profile, cand_doc, nlp=nlp)

    assert len(report.largest_gaps) == 6
    assert all(gap.score < 0.5 for gap in report.largest_gaps)
    keys = [(gap.score, gap.feature) for gap in report.largest_gaps]
    assert keys == sorted(keys)

    for gap in report.largest_gaps:
        expected_dir = "higher" if gap.candidate_value > gap.author_value else "lower"
        assert expected_dir in gap.explanation
        assert gap.feature in gap.explanation


def test_tc009_signature_and_frame_matches_reported_not_scored(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """TC-009: recurring_phrases, bounded_phrases, and sentence_frames reported uniquely sorted."""
    profile = copy.deepcopy(author_profile)
    profile["signature"] = {
        "recurring_phrases": ["at the edge", "in practice", "not present anywhere"],
        "bounded_phrases": ["when you need to", "in practice"],
        "sentence_frames": ["The result is ...", "Missing opener frame ..."],
    }

    cand_doc = _doc_from_paragraphs(
        [
            "IN PRACTICE, teams deploy small updates at the edge every week.",
            "The result is predictable latency when you need to scale quickly.",
            "Repeated in practice checks keep releases calm.",
        ]
    )
    report = score(profile, cand_doc, nlp=nlp)

    assert report.signature_matches == ("at the edge", "in practice", "when you need to")
    assert report.frame_matches == ("The result is ...",)

    # Confirm signature/frame matches do NOT alter numerical score
    profile_no_sig = copy.deepcopy(profile)
    profile_no_sig["signature"] = {
        "recurring_phrases": [],
        "bounded_phrases": [],
        "sentence_frames": [],
    }
    report_no_sig = score(profile_no_sig, cand_doc, nlp=nlp)
    assert report.overall == report_no_sig.overall
    assert report.dimensions == report_no_sig.dimensions
    assert report_no_sig.signature_matches == ()
    assert report_no_sig.frame_matches == ()


def test_function_words_zero_norm_returns_zero(
    author_profile: dict[str, Any],
    nlp: Any,
) -> None:
    """Zero-norm candidate function-word vector produces 0.0 cosine score safely."""
    no_fw_doc = _doc_from_paragraphs(["Bananas elephants xylophones zebras kangaroos."])
    report = score(author_profile, no_fw_doc, nlp=nlp)
    assert report.dimensions["function_words"] == 0.0


def test_match_band_thresholds(author_profile: dict[str, Any], nlp: Any) -> None:
    """Self-scoring against exact single-doc features yields STRONG (>=80), extreme yields DIFFERENT (<45)."""
    single_doc = _author_corpus_docs()[0]
    self_feats = analyze([single_doc], nlp=nlp)
    self_profile: dict[str, Any] = {
        "schema_version": 1,
        "corpus": {
            "document_count": 1,
            "total_words": self_feats["lexical"]["words"],
            "avg_doc_words": float(self_feats["lexical"]["words"]),
        },
        **self_feats,
    }
    self_report = score(self_profile, single_doc, nlp=nlp)
    assert self_report.overall == pytest.approx(100.0)
    assert self_report.band == MatchBand.STRONG
    assert self_report.largest_gaps == ()

    # Exact MatchBand boundary transitions
    assert _band_for_score(80.0) == MatchBand.STRONG
    assert _band_for_score(79.99) == MatchBand.CLOSE
    assert _band_for_score(65.0) == MatchBand.CLOSE
    assert _band_for_score(64.99) == MatchBand.PARTIAL
    assert _band_for_score(45.0) == MatchBand.PARTIAL
    assert _band_for_score(44.99) == MatchBand.DIFFERENT


def test_missing_signature_and_edge_frames(author_profile: dict[str, Any], nlp: Any) -> None:
    """Missing signature section and non-alpha/ellipsis-only frames are handled cleanly."""
    minimal_profile = copy.deepcopy(author_profile)
    minimal_profile.pop("signature", None)
    cand_doc = _doc_from_paragraphs(["2026 metrics confirm stable performance across nodes."])
    rep_min = score(minimal_profile, cand_doc, nlp=nlp)
    assert rep_min.signature_matches == ()
    assert rep_min.frame_matches == ()

    edge_profile = copy.deepcopy(author_profile)
    edge_profile["signature"] = {
        "recurring_phrases": None,
        "sentence_frames": ["...", "2026 ..."],
    }
    rep_edge = score(edge_profile, cand_doc, nlp=nlp)
    assert rep_edge.signature_matches == ()
    assert rep_edge.frame_matches == ("2026 ...",)

    bad_frames_profile = copy.deepcopy(author_profile)
    bad_frames_profile["signature"] = {"sentence_frames": None}
    rep_bad = score(bad_frames_profile, cand_doc, nlp=nlp)
    assert rep_bad.frame_matches == ()

