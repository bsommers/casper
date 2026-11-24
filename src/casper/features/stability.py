"""32-feature stability specification and cross-document variance calculation (Rank 2)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureSpec:
    """Metadata for one of the 32 scored voice conformance features."""

    key: str
    dimension: str
    weight: float
    floor: float
    profile_path: str


FEATURE_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec("mean_sentence_length", "rhythm", 2.0, 2.0, "sentences.length_words.mean"),
    FeatureSpec("short_sentence_rate", "rhythm", 1.0, 0.04, "sentences.short_rate_le8"),
    FeatureSpec("long_sentence_rate", "rhythm", 1.0, 0.04, "sentences.long_rate_ge30"),
    FeatureSpec("sentence_length_cv", "rhythm", 0.7, 0.08, "sentences.burstiness_cv"),
    FeatureSpec("passive_rate", "rhythm", 1.0, 0.08, "sentences.passive_rate"),
    FeatureSpec("commas_per_sentence", "rhythm", 0.7, 0.25, "sentences.commas_per_sentence"),
    FeatureSpec(
        "subordinate_clauses_per_sentence",
        "rhythm",
        0.7,
        0.20,
        "sentences.subordinate_clauses_per_sentence",
    ),
    FeatureSpec("fragment_rate", "rhythm", 0.7, 0.03, "sentences.fragment_rate"),
    FeatureSpec("question_rate", "rhythm", 0.7, 0.02, "sentences.question_rate"),
    FeatureSpec("exclamation_rate", "rhythm", 0.7, 0.01, "sentences.exclamation_rate"),
    FeatureSpec(
        "conjunction_start_rate", "openers", 0.7, 0.03, "sentences.starts.conjunction_rate"
    ),
    FeatureSpec("pronoun_start_rate", "openers", 0.8, 0.06, "sentences.starts.pronoun_rate"),
    FeatureSpec(
        "transition_start_rate",
        "openers",
        0.8,
        0.05,
        "sentences.starts.adverb_or_transition_rate",
    ),
    FeatureSpec(
        "sentences_per_paragraph", "paragraphs", 1.5, 0.60, "paragraphs.sentences_per_paragraph.mean"
    ),
    FeatureSpec(
        "single_sentence_paragraph_rate",
        "paragraphs",
        1.0,
        0.10,
        "paragraphs.single_sentence_rate",
    ),
    FeatureSpec("flesch_kincaid_grade", "register", 2.0, 1.20, "lexical.flesch_kincaid_grade"),
    FeatureSpec("mean_word_length", "register", 1.0, 0.15, "lexical.mean_word_length"),
    FeatureSpec("long_word_rate", "register", 0.7, 0.04, "lexical.long_word_rate_ge7"),
    FeatureSpec("acronyms_per_1k", "register", 0.8, 5.00, "lexical.acronyms_per_1k"),
    FeatureSpec(
        "first_person_singular_per_1k",
        "point_of_view",
        1.2,
        1.50,
        "voice.person_per_1k.first_singular",
    ),
    FeatureSpec(
        "first_person_plural_per_1k",
        "point_of_view",
        1.2,
        2.50,
        "voice.person_per_1k.first_plural_inclusive",
    ),
    FeatureSpec(
        "second_person_per_1k", "point_of_view", 1.2, 2.50, "voice.person_per_1k.second"
    ),
    FeatureSpec(
        "contractions_per_1k", "point_of_view", 1.2, 2.50, "voice.contractions_per_1k"
    ),
    FeatureSpec(
        "em_dashes_per_1k", "punctuation", 1.0, 1.50, "voice.punctuation_per_1k.em_dash"
    ),
    FeatureSpec("colons_per_1k", "punctuation", 1.0, 3.00, "voice.punctuation_per_1k.colon"),
    FeatureSpec(
        "semicolons_per_1k", "punctuation", 0.7, 1.50, "voice.punctuation_per_1k.semicolon"
    ),
    FeatureSpec(
        "parentheses_per_1k",
        "punctuation",
        0.7,
        2.00,
        "voice.punctuation_per_1k.parenthetical",
    ),
    FeatureSpec("commas_per_1k", "punctuation", 0.7, 8.00, "voice.commas_per_1k"),
    FeatureSpec(
        "transitions_per_1k", "rhetoric", 0.8, 3.00, "voice.lexicon_per_1k.transitions"
    ),
    FeatureSpec(
        "intensifiers_per_1k", "rhetoric", 0.8, 3.00, "voice.lexicon_per_1k.intensifiers"
    ),
    FeatureSpec("hedges_per_1k", "rhetoric", 0.8, 3.00, "voice.lexicon_per_1k.hedges"),
    FeatureSpec(
        "contrast_frames_per_1k", "rhetoric", 0.8, 1.00, "voice.rhetoric.contrast_frames_per_1k"
    ),
)

STABILITY_KEYS: tuple[str, ...] = tuple(spec.key for spec in FEATURE_SPECS)

FEATURE_SPEC_BY_KEY: dict[str, FeatureSpec] = {spec.key: spec for spec in FEATURE_SPECS}

DIMENSION_WEIGHTS: dict[str, float] = {
    "rhythm": 1.5,
    "openers": 0.7,
    "paragraphs": 0.8,
    "register": 1.2,
    "point_of_view": 1.2,
    "punctuation": 1.0,
    "rhetoric": 0.9,
    "function_words": 1.2,
    "structure": 0.8,
}


def extract_path(mapping: dict[str, Any], dotted_path: str) -> float:
    """Resolve a dotted feature path (e.g. 'sentences.length_words.mean') to a float."""
    cur: Any = mapping
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return 0.0
        cur = cur[part]
    return float(cur)


def extract_stability_vector(features: dict[str, Any]) -> dict[str, float]:
    """Extract all 32 scored scalar feature values from a features/profile dict."""
    return {spec.key: extract_path(features, spec.profile_path) for spec in FEATURE_SPECS}


def compute_stability(per_doc_features: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Compute per-feature {min, max, stdev} across individual documents."""
    vectors = [extract_stability_vector(df) for df in per_doc_features]
    result: dict[str, dict[str, float]] = {}
    for key in STABILITY_KEYS:
        vals = [vec[key] for vec in vectors]
        if not vals:
            result[key] = {"min": 0.0, "max": 0.0, "stdev": 0.0}
        elif len(vals) == 1:
            v = round(vals[0], 4)
            result[key] = {"min": v, "max": v, "stdev": 0.0}
        else:
            result[key] = {
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
                "stdev": round(statistics.stdev(vals), 4),
            }
    return result
