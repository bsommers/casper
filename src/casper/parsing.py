"""Cached spaCy language pipeline loader (Rank 1)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import spacy

from casper.errors import InputError

MODEL_NAME = "en_core_web_sm"


@lru_cache(maxsize=2)
def load_nlp(*, ner: bool = False) -> Any:
    """Load and cache the pinned spaCy en_core_web_sm pipeline.

    When ner=False (default), NER is disabled for faster voice analysis.
    """
    disable = [] if ner else ["ner"]
    try:
        return spacy.load(MODEL_NAME, disable=disable)
    except OSError as exc:
        raise InputError(
            f"spaCy model {MODEL_NAME!r} is not installed. Run `uv pip install -e .`."
        ) from exc
