"""Sentence and paragraph rhythm feature extractor (Rank 2)."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence
from typing import Any

from casper.models import Block, BlockKind

_PASSIVE_DEPS = frozenset({"nsubjpass", "auxpass", "csubjpass"})
_SUBORDINATE_DEPS = frozenset({"advcl", "acl", "relcl", "ccomp", "xcomp", "csubj"})
_FINITE_TAGS = frozenset({"VBP", "VBZ", "VBD", "MD"})
_CONJ_STARTS = frozenset({"and", "but", "or", "so", "yet", "nor", "for"})
_PRON_STARTS = frozenset(
    {"i", "we", "you", "he", "she", "it", "they", "this", "that", "these", "those"}
)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo]))


def _is_word_token(tok: Any) -> bool:
    return bool(not tok.is_space and not tok.is_punct and any(ch.isalnum() for ch in tok.text))


def _has_finite_verb(sent: Any) -> bool:
    for tok in sent:
        if tok.pos_ in {"VERB", "AUX"}:
            if "Fin" in tok.morph.get("VerbForm") or tok.tag_ in _FINITE_TAGS:
                return True
    return False


def extract_sentences_and_paragraphs(
    parsed_blocks: Sequence[tuple[Block, Any]],
    transitions: frozenset[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute `sentences` and `paragraphs` feature groups from parsed prose blocks."""
    sent_lengths: list[int] = []
    passive_count = 0
    subordinate_total = 0
    comma_total = 0
    fragment_count = 0
    question_count = 0
    exclamation_count = 0
    conj_start_count = 0
    pron_start_count = 0
    adv_or_trans_start_count = 0
    first_word_counts: Counter[str] = Counter()

    para_sent_counts: list[int] = []
    para_word_counts: list[int] = []

    for block, sp_doc in parsed_blocks:
        block_sents = 0
        block_words = 0
        for sent in sp_doc.sents:
            words = [t for t in sent if _is_word_token(t)]
            if not words:
                continue
            wcount = len(words)
            block_sents += 1
            block_words += wcount
            sent_lengths.append(wcount)

            if any(t.dep_ in _PASSIVE_DEPS for t in sent):
                passive_count += 1
            subordinate_total += sum(1 for t in sent if t.dep_ in _SUBORDINATE_DEPS)
            comma_total += sum(1 for t in sent if t.text == ",")
            if not _has_finite_verb(sent):
                fragment_count += 1

            stripped = sent.text.strip()
            if stripped.endswith("?"):
                question_count += 1
            elif stripped.endswith("!"):
                exclamation_count += 1

            first = words[0]
            low = first.text.lower()
            first_word_counts[first.text] += 1
            if first.pos_ in {"CCONJ", "SCONJ"} or low in _CONJ_STARTS:
                conj_start_count += 1
            if first.pos_ == "PRON" or low in _PRON_STARTS:
                pron_start_count += 1
            if first.pos_ == "ADV" or low in transitions:
                adv_or_trans_start_count += 1

        if block.kind == BlockKind.PARAGRAPH and block_sents > 0:
            para_sent_counts.append(block_sents)
            para_word_counts.append(block_words)

    scount = len(sent_lengths)
    if scount == 0:
        sentences_dict: dict[str, Any] = {
            "count": 0,
            "length_words": {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0, "stdev": 0.0},
            "short_rate_le8": 0.0,
            "long_rate_ge30": 0.0,
            "burstiness_cv": 0.0,
            "passive_rate": 0.0,
            "subordinate_clauses_per_sentence": 0.0,
            "commas_per_sentence": 0.0,
            "fragment_rate": 0.0,
            "question_rate": 0.0,
            "exclamation_rate": 0.0,
            "starts": {
                "conjunction_rate": 0.0,
                "pronoun_rate": 0.0,
                "adverb_or_transition_rate": 0.0,
                "top_first_words": [],
            },
        }
    else:
        sorted_lens = sorted(float(x) for x in sent_lengths)
        mean_len = statistics.fmean(sorted_lens)
        median_len = statistics.median(sorted_lens)
        stdev_len = statistics.stdev(sorted_lens) if scount >= 2 else 0.0
        cv = (stdev_len / mean_len) if mean_len > 0 else 0.0
        top_first = [
            [word, cnt]
            for word, cnt in sorted(first_word_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
        ]
        sentences_dict = {
            "count": scount,
            "length_words": {
                "mean": round(mean_len, 4),
                "median": round(median_len, 4),
                "p10": round(_percentile(sorted_lens, 10.0), 4),
                "p90": round(_percentile(sorted_lens, 90.0), 4),
                "stdev": round(stdev_len, 4),
            },
            "short_rate_le8": round(sum(1 for x in sent_lengths if x <= 8) / scount, 4),
            "long_rate_ge30": round(sum(1 for x in sent_lengths if x >= 30) / scount, 4),
            "burstiness_cv": round(cv, 4),
            "passive_rate": round(passive_count / scount, 4),
            "subordinate_clauses_per_sentence": round(subordinate_total / scount, 4),
            "commas_per_sentence": round(comma_total / scount, 4),
            "fragment_rate": round(fragment_count / scount, 4),
            "question_rate": round(question_count / scount, 4),
            "exclamation_rate": round(exclamation_count / scount, 4),
            "starts": {
                "conjunction_rate": round(conj_start_count / scount, 4),
                "pronoun_rate": round(pron_start_count / scount, 4),
                "adverb_or_transition_rate": round(adv_or_trans_start_count / scount, 4),
                "top_first_words": top_first,
            },
        }

    pcount = len(para_sent_counts)
    if pcount == 0:
        paragraphs_dict: dict[str, Any] = {
            "count": 0,
            "sentences_per_paragraph": {"mean": 0.0, "median": 0.0},
            "words_per_paragraph": {"mean": 0.0, "median": 0.0},
            "single_sentence_rate": 0.0,
            "long_paragraph_rate_ge120w": 0.0,
        }
    else:
        paragraphs_dict = {
            "count": pcount,
            "sentences_per_paragraph": {
                "mean": round(statistics.fmean(para_sent_counts), 4),
                "median": round(float(statistics.median(para_sent_counts)), 4),
            },
            "words_per_paragraph": {
                "mean": round(statistics.fmean(para_word_counts), 4),
                "median": round(float(statistics.median(para_word_counts)), 4),
            },
            "single_sentence_rate": round(sum(1 for x in para_sent_counts if x == 1) / pcount, 4),
            "long_paragraph_rate_ge120w": round(
                sum(1 for x in para_word_counts if x >= 120) / pcount, 4
            ),
        }

    return sentences_dict, paragraphs_dict
