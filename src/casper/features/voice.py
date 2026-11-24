"""Voice, point-of-view, punctuation, rhetoric, and typography extractor (Rank 2)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from casper.models import Block

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)*")
_CONTRACTION_RE = re.compile(
    r"\b(?:[a-z]+n't|"
    r"(?:i|you|we|they|he|she|it|that|there|here|what|who|where|when|how|let)'(?:m|re|ve|ll|d|s)|"
    r"[a-z]+'(?:re|ve|ll|d))\b",
    re.IGNORECASE,
)
_EM_DASH_RE = re.compile(r"\u2014|(?<!-)--(?!-)")
_COLON_RE = re.compile(r"(?<!\d):(?![/\d])")
_QUOTE_SPAN_RE = re.compile(r'"[^"\n]+"|\u201c[^\u201d\n]+\u201d')
_OXFORD_RE = re.compile(r",\s+[A-Za-z0-9'-]+,\s+(?:and|or)\s+[A-Za-z0-9'-]+", re.IGNORECASE)
_NON_OXFORD_RE = re.compile(
    r"(?<!,)\s+[A-Za-z0-9'-]+,\s+[A-Za-z0-9'-]+\s+(?:and|or)\s+[A-Za-z0-9'-]+", re.IGNORECASE
)
_CONTRAST_RE = re.compile(
    r"\bnot\s+(?:just\s+|only\s+)?[^.!?;:\n]{1,60}(?:,\s*but\b|;\s*(?:it\s+is|it's|they\s+are|rather)\b)"
    r"|\brather\s+than\s+[^.,;!?\n]{1,50},"
    r"|\binstead\s+of\s+[^.,;!?\n]{1,50},",
    re.IGNORECASE,
)
_ACRONYM_INTRO_RE = re.compile(
    r"\b[A-Z][a-z]+(?:\s+(?:of|the|for|and|in|on|to|[A-Z][a-z]+)){1,5}\s*\(([A-Z]{2,6})\)"
)

_FIRST_SINGULAR = frozenset({"i", "me", "my", "mine", "myself", "i'm", "i've", "i'll", "i'd"})
_FIRST_PLURAL = frozenset({"we", "us", "our", "ours", "ourselves", "we're", "we've", "we'll", "we'd"})
_SECOND_PERSON = frozenset(
    {"you", "your", "yours", "yourself", "yourselves", "you're", "you've", "you'll", "you'd"}
)
_THIRD_PLURAL = frozenset(
    {"they", "them", "their", "theirs", "themselves", "they're", "they've", "they'll", "they'd"}
)


def _normalize_apostrophes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def _detect_quote_style(raw_text: str) -> str:
    has_straight = '"' in raw_text
    has_curly = ("\u201c" in raw_text) or ("\u201d" in raw_text)
    if not has_straight and not has_curly:
        has_straight = "'" in raw_text
        has_curly = ("\u2018" in raw_text) or ("\u2019" in raw_text)
    if has_straight and has_curly:
        return "mixed"
    if has_straight:
        return "straight"
    if has_curly:
        return "curly"
    return "none"


def extract_voice_and_typography(
    prose_blocks: Sequence[Block],
    lexicons: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute `voice` and `typography` feature groups from non-excluded prose blocks."""
    raw_text = "\n\n".join(b.text for b in prose_blocks if b.text.strip())
    norm_text = _normalize_apostrophes(raw_text)
    words = _WORD_RE.findall(norm_text)
    total_words = len(words)
    total_links = sum(b.links for b in prose_blocks)

    quote_style = _detect_quote_style(raw_text)

    if total_words == 0:
        voice_dict: dict[str, Any] = {
            "person_per_1k": {
                "first_singular": 0.0,
                "first_plural_inclusive": 0.0,
                "second": 0.0,
                "third_plural": 0.0,
            },
            "contractions_per_1k": 0.0,
            "negations_per_1k": 0.0,
            "punctuation_per_1k": {
                "em_dash": 0.0,
                "colon": 0.0,
                "semicolon": 0.0,
                "parenthetical": 0.0,
                "quotes": 0.0,
            },
            "commas_per_1k": 0.0,
            "oxford_comma_rate": 0.0,
            "lexicon_per_1k": {
                "transitions": 0.0,
                "intensifiers": 0.0,
                "hedges": 0.0,
            },
            "rhetoric": {
                "contrast_frames_per_1k": 0.0,
                "acronym_introductions": 0,
            },
        }
        typography_dict: dict[str, Any] = {
            "quote_style": quote_style,
            "links_per_1k": 0.0,
        }
        return voice_dict, typography_dict

    scale = 1000.0 / total_words
    lower_counts: Counter[str] = Counter(w.lower() for w in words)

    first_sing = sum(lower_counts.get(w, 0) for w in _FIRST_SINGULAR)
    first_plur = sum(lower_counts.get(w, 0) for w in _FIRST_PLURAL)
    second_p = sum(lower_counts.get(w, 0) for w in _SECOND_PERSON)
    third_plur = sum(lower_counts.get(w, 0) for w in _THIRD_PLURAL)

    contractions = len(_CONTRACTION_RE.findall(norm_text))
    neg_set = frozenset(lexicons.get("negations", ()))
    trans_set = frozenset(lexicons.get("transitions", ()))
    int_set = frozenset(lexicons.get("intensifiers", ()))
    hedge_set = frozenset(lexicons.get("hedges", ()))

    negations = sum(lower_counts.get(w, 0) for w in neg_set)
    transitions = sum(lower_counts.get(w, 0) for w in trans_set)
    intensifiers = sum(lower_counts.get(w, 0) for w in int_set)
    hedges = sum(lower_counts.get(w, 0) for w in hedge_set)

    em_dashes = len(_EM_DASH_RE.findall(raw_text))
    colons = len(_COLON_RE.findall(raw_text))
    semicolons = raw_text.count(";")
    parentheticals = raw_text.count("(")
    quotes = len(_QUOTE_SPAN_RE.findall(raw_text))
    commas = raw_text.count(",")

    oxford_hits = len(_OXFORD_RE.findall(norm_text))
    non_oxford_hits = len(_NON_OXFORD_RE.findall(norm_text))
    oxford_denom = oxford_hits + non_oxford_hits
    oxford_rate = (oxford_hits / oxford_denom) if oxford_denom > 0 else 0.0

    contrast_frames = len(_CONTRAST_RE.findall(norm_text))
    acronym_intros = len(_ACRONYM_INTRO_RE.findall(raw_text))

    voice_dict = {
        "person_per_1k": {
            "first_singular": round(first_sing * scale, 4),
            "first_plural_inclusive": round(first_plur * scale, 4),
            "second": round(second_p * scale, 4),
            "third_plural": round(third_plur * scale, 4),
        },
        "contractions_per_1k": round(contractions * scale, 4),
        "negations_per_1k": round(negations * scale, 4),
        "punctuation_per_1k": {
            "em_dash": round(em_dashes * scale, 4),
            "colon": round(colons * scale, 4),
            "semicolon": round(semicolons * scale, 4),
            "parenthetical": round(parentheticals * scale, 4),
            "quotes": round(quotes * scale, 4),
        },
        "commas_per_1k": round(commas * scale, 4),
        "oxford_comma_rate": round(oxford_rate, 4),
        "lexicon_per_1k": {
            "transitions": round(transitions * scale, 4),
            "intensifiers": round(intensifiers * scale, 4),
            "hedges": round(hedges * scale, 4),
        },
        "rhetoric": {
            "contrast_frames_per_1k": round(contrast_frames * scale, 4),
            "acronym_introductions": acronym_intros,
        },
    }

    typography_dict = {
        "quote_style": quote_style,
        "links_per_1k": round(total_links * scale, 4),
    }
    return voice_dict, typography_dict
