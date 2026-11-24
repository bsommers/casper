"""Shared RewriteRule registry and declared token allow-list (Rank 1, ADR 0012).

Imported downward by both realizer.py and validator.py so validator never imports realizer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from casper.models import RewriteRule

TOKEN_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)*")

_CONTRACTIONS: tuple[tuple[str, str], ...] = (
    ("do not", "don't"),
    ("does not", "doesn't"),
    ("did not", "didn't"),
    ("it is", "it's"),
    ("we are", "we're"),
    ("they are", "they're"),
    ("is not", "isn't"),
    ("are not", "aren't"),
    ("cannot", "can't"),
    ("will not", "won't"),
    ("have not", "haven't"),
    ("has not", "hasn't"),
)

_TRANSITION_OPENERS: tuple[str, ...] = (
    "Also,",
    "Next,",
    "Additionally,",
    "Finally,",
)

_TRANSITION_START_WORDS: frozenset[str] = frozenset(
    {
        "however",
        "therefore",
        "moreover",
        "furthermore",
        "meanwhile",
        "consequently",
        "additionally",
        "instead",
        "otherwise",
        "nonetheless",
        "nevertheless",
        "similarly",
        "finally",
        "next",
        "also",
        "still",
        "then",
        "thus",
        "yet",
    }
)


def _match_case(template: str, replacement: str) -> str:
    if template.isupper():
        return replacement.upper()
    if template and template[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _replace_phrase(text: str, src: str, dst: str) -> str:
    pattern = re.compile(rf"(?<!\w){re.escape(src)}(?!\w)", re.IGNORECASE)
    return pattern.sub(lambda m: _match_case(m.group(0), dst), text)


def _apply_plain(text: str) -> list[str]:
    return [text]


def _apply_contract(text: str) -> list[str]:
    updated = text
    for full, short in _CONTRACTIONS:
        updated = _replace_phrase(updated, full, short)
    return [updated] if updated != text else []


def _apply_expand(text: str) -> list[str]:
    updated = text
    for full, short in _CONTRACTIONS:
        updated = _replace_phrase(updated, short, full)
    return [updated] if updated != text else []


def _first_word(text: str) -> str:
    m = TOKEN_RE.match(text.lstrip())
    return m.group(0) if m else ""


def should_preserve_initial_case(text: str, protected_names: Iterable[str] = ()) -> bool:
    """Return True if the first token of text is a proper noun, acronym, or 'I'."""
    word = _first_word(text)
    if not word:
        return True
    if word == "I":
        return True
    if len(word) >= 2 and word.isupper():
        return True
    if any(ch.isupper() for ch in word[1:]):
        return True
    protected_tokens: set[str] = set()
    for name in protected_names:
        for tok in TOKEN_RE.findall(name):
            protected_tokens.add(tok.lower())
    return word.lower() in protected_tokens


def maybe_lowercase_start(text: str, protected_names: Iterable[str] = ()) -> str:
    stripped = text.lstrip()
    if not stripped:
        return stripped
    if should_preserve_initial_case(stripped, protected_names):
        return stripped
    return stripped[0].lower() + stripped[1:]


def _apply_transition_opener(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    first = _first_word(stripped).lower()
    if first in _TRANSITION_START_WORDS:
        return []
    out: list[str] = []
    for opener in _TRANSITION_OPENERS:
        out.append(f"{opener} {stripped}")
    return out


def apply_transition_opener_with_names(
    text: str, protected_names: Iterable[str] = ()
) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    first = _first_word(stripped).lower()
    if first in _TRANSITION_START_WORDS:
        return []
    body = maybe_lowercase_start(stripped, protected_names)
    return [f"{opener} {body}" for opener in _TRANSITION_OPENERS]


def merge_pair_semicolon(
    first_sentence: str,
    second_sentence: str,
    *,
    protected_names: Iterable[str] = (),
) -> str | None:
    """Merge two short (<=12 words each) sentences with '; ' preserving proper nouns."""
    s1 = first_sentence.strip()
    s2 = second_sentence.strip()
    if not s1 or not s2:
        return None
    if len(s1.split()) > 12 or len(s2.split()) > 12:
        return None
    if s1[-1] in "?!":
        return None
    if _first_word(s2).lower() in _TRANSITION_START_WORDS:
        return None
    s1_core = s1.rstrip(".")
    s2_body = maybe_lowercase_start(s2, protected_names)
    return f"{s1_core}; {s2_body}"


def _apply_semicolon_noop(text: str) -> list[str]:
    # Section-level merge is driven via merge_pair_semicolon(); per-sentence hook is identity.
    return []


_CONTRACT_ADDED = frozenset(short.lower() for _, short in _CONTRACTIONS)
_EXPAND_ADDED = frozenset(
    tok.lower() for full, _ in _CONTRACTIONS for tok in TOKEN_RE.findall(full)
)
_TRANSITION_ADDED = frozenset(
    tok.lower() for opener in _TRANSITION_OPENERS for tok in TOKEN_RE.findall(opener)
)

REWRITE_RULES: tuple[RewriteRule, ...] = (
    RewriteRule(
        id="plain",
        description="Identity rewrite preserving original sentence wording.",
        added_tokens=frozenset(),
        apply=_apply_plain,
    ),
    RewriteRule(
        id="contract",
        description="Apply standard English contractions.",
        added_tokens=_CONTRACT_ADDED,
        apply=_apply_contract,
    ),
    RewriteRule(
        id="expand",
        description="Expand standard English contractions to full forms.",
        added_tokens=_EXPAND_ADDED,
        apply=_apply_expand,
    ),
    RewriteRule(
        id="transition_opener",
        description="Prepend a non-initial transition opener (Also/Next/Additionally/Finally).",
        added_tokens=_TRANSITION_ADDED,
        apply=_apply_transition_opener,
    ),
    RewriteRule(
        id="semicolon_merge",
        description="Merge first two short consecutive sentences with a semicolon.",
        added_tokens=frozenset(),
        apply=_apply_semicolon_noop,
    ),
)

ALLOWED_RULE_TOKENS: frozenset[str] = frozenset().union(
    *(rule.added_tokens for rule in REWRITE_RULES)
)
