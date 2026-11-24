"""Lexical register, readability, and 60-function-word distribution extractor (Rank 2)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from casper.models import Block

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)*")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")
_ACRONYM_RE = re.compile(r"^[A-Z]{2,}s?$")


def count_syllables(word: str) -> int:
    """Deterministic English syllable count estimator."""
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 1
    if len(cleaned) <= 3:
        return 1
    if cleaned.endswith("e") and not cleaned.endswith(("le", "ye")):
        cleaned = cleaned[:-1]
    groups = _VOWEL_GROUP_RE.findall(cleaned)
    return max(1, len(groups))


def _normalize_apostrophes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def extract_lexical(
    prose_blocks: Sequence[Block],
    sentence_count: int,
    function_words: Sequence[str],
) -> tuple[dict[str, Any], dict[str, float]]:
    """Compute `lexical` metrics and `function_word_per_1k` over prose blocks."""
    words: list[str] = []
    for block in prose_blocks:
        words.extend(_WORD_RE.findall(_normalize_apostrophes(block.text)))

    total_words = len(words)
    lower_counts: Counter[str] = Counter(w.lower() for w in words)

    if total_words == 0:
        lexical_dict: dict[str, Any] = {
            "words": 0,
            "flesch_kincaid_grade": 0.0,
            "flesch_reading_ease": 0.0,
            "mean_word_length": 0.0,
            "long_word_rate_ge7": 0.0,
            "acronyms_per_1k": 0.0,
        }
        fw_rates = {fw: 0.0 for fw in function_words}
        return lexical_dict, fw_rates

    total_chars = sum(len(w) for w in words)
    long_words = sum(1 for w in words if len(w) >= 7)
    acronyms = sum(1 for w in words if _ACRONYM_RE.match(w))

    if sentence_count > 0:
        total_syllables = sum(count_syllables(w) for w in words)
        wps = total_words / sentence_count
        spw = total_syllables / total_words
        fk_grade = 0.39 * wps + 11.8 * spw - 15.59
        flesch_ease = 206.835 - 1.015 * wps - 84.6 * spw
    else:
        fk_grade = 0.0
        flesch_ease = 0.0

    scale = 1000.0 / total_words
    lexical_dict = {
        "words": total_words,
        "flesch_kincaid_grade": round(fk_grade, 4),
        "flesch_reading_ease": round(flesch_ease, 4),
        "mean_word_length": round(total_chars / total_words, 4),
        "long_word_rate_ge7": round(long_words / total_words, 4),
        "acronyms_per_1k": round(acronyms * scale, 4),
    }

    fw_rates = {fw: round(lower_counts.get(fw, 0) * scale, 4) for fw in function_words}
    return lexical_dict, fw_rates
