"""Signature phrases, sentence frames, and exemplar extractor (Rank 2)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")


def _normalize_apostrophes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def _clean_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def extract_signature_and_exemplars(
    per_doc_sentences: Sequence[Sequence[str]],
    function_words: frozenset[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute `signature` phrases/frames and `exemplars` across documents."""
    ngram_doc_freq: Counter[str] = Counter()
    ngram_total_freq: Counter[str] = Counter()
    bounded_freq: Counter[str] = Counter()
    frame_freq: Counter[str] = Counter()

    openers: list[str] = []
    closers: list[str] = []
    short_lines: list[str] = []
    seen_openers: set[str] = set()
    seen_closers: set[str] = set()
    seen_shorts: set[str] = set()

    for doc_sents in per_doc_sentences:
        cleaned_sents = [_clean_sentence(s) for s in doc_sents if _clean_sentence(s)]
        if not cleaned_sents:
            continue

        # Exemplar opener & closer from document boundaries
        first_s = cleaned_sents[0]
        first_words = _WORD_RE.findall(_normalize_apostrophes(first_s))
        if 4 <= len(first_words) <= 30 and first_s not in seen_openers and len(openers) < 4:
            seen_openers.add(first_s)
            openers.append(first_s)

        last_s = cleaned_sents[-1]
        last_words = _WORD_RE.findall(_normalize_apostrophes(last_s))
        if 4 <= len(last_words) <= 30 and last_s not in seen_closers and len(closers) < 4:
            seen_closers.add(last_s)
            closers.append(last_s)

        doc_ngrams: set[str] = set()
        for sent in cleaned_sents:
            norm_words = [w.lower() for w in _WORD_RE.findall(_normalize_apostrophes(sent))]
            raw_words = _WORD_RE.findall(_normalize_apostrophes(sent))

            if (
                2 <= len(raw_words) <= 8
                and sent[-1] in ".!?"
                and sent not in seen_shorts
                and len(short_lines) < 4
            ):
                seen_shorts.add(sent)
                short_lines.append(sent)

            # Sentence opener frames (first 3 words if sentence has >= 5 words)
            if len(raw_words) >= 5:
                frame = " ".join(raw_words[:3]) + " ..."
                frame_freq[frame] += 1

            # 2..4-grams for recurring_phrases
            n_words = len(norm_words)
            for n in (2, 3, 4):
                for i in range(n_words - n + 1):
                    gram_tokens = norm_words[i : i + n]
                    if all(t in function_words for t in gram_tokens):
                        continue
                    phrase = " ".join(gram_tokens)
                    ngram_total_freq[phrase] += 1
                    doc_ngrams.add(phrase)

            # Function-word-bounded 3..4-grams
            for n in (3, 4):
                for i in range(n_words - n + 1):
                    gram_tokens = norm_words[i : i + n]
                    if gram_tokens[0] in function_words and gram_tokens[-1] in function_words:
                        if any(t not in function_words for t in gram_tokens[1:-1]):
                            bounded_freq[" ".join(gram_tokens)] += 1

        for phrase in doc_ngrams:
            ngram_doc_freq[phrase] += 1

    # Select top <= 12 recurring phrases appearing in >= 2 documents
    recurring_candidates = [
        (phrase, df, ngram_total_freq[phrase])
        for phrase, df in ngram_doc_freq.items()
        if df >= 2
    ]
    recurring_candidates.sort(key=lambda item: (-item[1], -item[2], -len(item[0].split()), item[0]))
    recurring_phrases: list[str] = []
    for phrase, _df, _tf in recurring_candidates:
        if any(phrase in existing for existing in recurring_phrases):
            continue
        recurring_phrases.append(phrase)
        if len(recurring_phrases) >= 12:
            break

    # Select top <= 12 bounded phrases appearing >= 2 times
    bounded_candidates = [(p, cnt) for p, cnt in bounded_freq.items() if cnt >= 2]
    bounded_candidates.sort(key=lambda item: (-item[1], item[0]))
    bounded_phrases = [p for p, _ in bounded_candidates[:12]]

    # Select top <= 8 recurring sentence frames appearing >= 2 times
    frame_candidates = [(f, cnt) for f, cnt in frame_freq.items() if cnt >= 2]
    frame_candidates.sort(key=lambda item: (-item[1], item[0]))
    sentence_frames = [f for f, _ in frame_candidates[:8]]

    signature_dict: dict[str, Any] = {
        "recurring_phrases": recurring_phrases,
        "bounded_phrases": bounded_phrases,
        "sentence_frames": sentence_frames,
    }
    exemplars_dict: dict[str, Any] = {
        "openers": openers,
        "closers": closers,
        "short_lines": short_lines,
    }
    return signature_dict, exemplars_dict
