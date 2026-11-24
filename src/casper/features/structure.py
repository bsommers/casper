"""Headings, lists, and document-structure feature extractor (Rank 2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from casper.documents import count_words, heading_blocks, list_blocks, prose_word_count
from casper.models import BlockKind, Document

_ALPHA_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_MINOR_TITLE_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "but",
        "or",
        "nor",
        "for",
        "yet",
        "so",
        "in",
        "on",
        "at",
        "to",
        "from",
        "by",
        "of",
        "with",
        "as",
        "per",
        "via",
    }
)
_ACTION_CLOSE_RE = re.compile(
    r"\b(?:start|measure|try|check|review|build|run|keep|focus|use|make|send|share|"
    r"let\s+us|let\s+me|please|next\s+step|verify|ship|test|audit)\b",
    re.IGNORECASE,
)
_SUMMARY_CLOSE_RE = re.compile(
    r"\b(?:in\s+short|in\s+summary|overall|ultimately|to\s+sum\s+up|bottom\s+line|"
    r"takeaway|result|therefore|thus|consequently)\b",
    re.IGNORECASE,
)


def _classify_heading_case(text: str) -> str | None:
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return None
    if len(alpha_chars) >= 2 and all(c.isupper() for c in alpha_chars):
        return "upper"

    words = _ALPHA_WORD_RE.findall(text)
    if not words:
        return None
    if len(words) == 1:
        return "sentence"

    major_words = [
        w
        for idx, w in enumerate(words)
        if idx == 0 or idx == len(words) - 1 or w.lower() not in _MINOR_TITLE_WORDS
    ]
    cap_major = sum(1 for w in major_words if w[0].isupper())
    cap_total = sum(1 for w in words if w[0].isupper())
    if cap_total >= 2 and cap_major / max(len(major_words), 1) >= 0.75:
        return "title"
    return "sentence"


def _classify_closing_sentence(sent_text: str) -> str | None:
    text = sent_text.strip()
    if not text:
        return None
    if text.endswith("?"):
        return "question"
    if _ACTION_CLOSE_RE.search(text):
        return "action"
    if _SUMMARY_CLOSE_RE.search(text):
        return "summary"
    return "reflection"


def extract_structure_features(
    docs: Sequence[Document],
    total_prose_words: int,
    last_sentences_per_doc: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Compute `headings`, `lists`, and `structure` feature groups."""
    all_headings = [b for doc in docs for b in heading_blocks(doc)]
    all_lists = [b for doc in docs for b in list_blocks(doc)]

    scale = (1000.0 / total_prose_words) if total_prose_words > 0 else 0.0

    # Headings
    h_count = len(all_headings)
    if h_count == 0:
        headings_dict: dict[str, Any] = {
            "count": 0,
            "density_per_1k": 0.0,
            "mean_words": 0.0,
            "case_style": "none",
            "case_shares": {"sentence": 0.0, "title": 0.0, "upper": 0.0},
        }
    else:
        mean_h_words = sum(count_words(b.text) for b in all_headings) / h_count
        case_counts = {"sentence": 0, "title": 0, "upper": 0}
        classified = 0
        for b in all_headings:
            label = _classify_heading_case(b.text)
            if label is not None:
                case_counts[label] += 1
                classified += 1
        if classified == 0:
            shares = {"sentence": 0.0, "title": 0.0, "upper": 0.0}
            case_style = "none"
        else:
            shares = {k: round(v / classified, 4) for k, v in case_counts.items()}
            dominant = [k for k, s in shares.items() if s >= 0.65]
            case_style = dominant[0] if len(dominant) == 1 else "mixed"

        headings_dict = {
            "count": h_count,
            "density_per_1k": round(h_count * scale, 4),
            "mean_words": round(mean_h_words, 4),
            "case_style": case_style,
            "case_shares": shares,
        }

    # Lists
    l_count = len(all_lists)
    if l_count == 0:
        lists_dict: dict[str, Any] = {
            "item_count": 0,
            "items_per_1k": 0.0,
            "emphasis_lead_rate": 0.0,
        }
    else:
        emph = sum(1 for b in all_lists if b.emphasis_lead)
        lists_dict = {
            "item_count": l_count,
            "items_per_1k": round(l_count * scale, 4),
            "emphasis_lead_rate": round(emph / l_count, 4),
        }

    # Structure
    doc_count = len(docs)
    if doc_count == 0:
        structure_dict: dict[str, Any] = {
            "mean_doc_words": 0.0,
            "mean_sections": 0.0,
            "has_summary_rate": 0.0,
            "closing_patterns": [],
        }
    else:
        mean_doc_words = sum(prose_word_count(d) for d in docs) / doc_count
        mean_sections = h_count / doc_count
        summary_docs = sum(1 for d in docs if any(b.kind == BlockKind.SUMMARY for b in d.blocks))
        seen_patterns: set[str] = set()
        for sent in last_sentences_per_doc:
            pat = _classify_closing_sentence(sent)
            if pat is not None:
                seen_patterns.add(pat)
        ordered_patterns = [
            p for p in ("question", "action", "summary", "reflection") if p in seen_patterns
        ]
        structure_dict = {
            "mean_doc_words": round(mean_doc_words, 2),
            "mean_sections": round(mean_sections, 4),
            "has_summary_rate": round(summary_docs / doc_count, 4),
            "closing_patterns": ordered_patterns,
        }

    return headings_dict, lists_dict, structure_dict
