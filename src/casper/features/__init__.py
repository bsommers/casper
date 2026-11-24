"""Linguistic feature extraction package orchestrating all 11 feature groups + stability (Rank 2)."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from casper.documents import prose_blocks
from casper.features.lexical import extract_lexical
from casper.features.sentences import extract_sentences_and_paragraphs
from casper.features.signature import extract_signature_and_exemplars
from casper.features.stability import (
    DIMENSION_WEIGHTS,
    FEATURE_SPEC_BY_KEY,
    FEATURE_SPECS,
    STABILITY_KEYS,
    FeatureSpec,
    compute_stability,
    extract_path,
    extract_stability_vector,
)
from casper.features.structure import extract_structure_features
from casper.features.voice import extract_voice_and_typography
from casper.libraries import load_libraries
from casper.models import Block, Document
from casper.parsing import load_nlp

__all__ = [
    "DIMENSION_WEIGHTS",
    "FEATURE_SPECS",
    "FEATURE_SPEC_BY_KEY",
    "FeatureSpec",
    "STABILITY_KEYS",
    "analyze",
    "compute_stability",
    "extract_path",
    "extract_stability_vector",
]


@lru_cache(maxsize=1)
def _default_lexicons() -> dict[str, tuple[str, ...]]:
    return load_libraries().lexicons


def _analyze_core(
    docs: Sequence[Document],
    per_doc_parsed: Sequence[list[tuple[Block, Any]]],
    lexicons: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    all_parsed: list[tuple[Block, Any]] = [
        item for doc_items in per_doc_parsed for item in doc_items
    ]
    all_prose_blocks: list[Block] = [blk for blk, _sp in all_parsed]

    transitions = frozenset(lexicons.get("transitions", ()))
    function_words = lexicons.get("function_words", ())
    function_word_set = frozenset(function_words)

    sentences_dict, paragraphs_dict = extract_sentences_and_paragraphs(all_parsed, transitions)
    lexical_dict, fw_rates = extract_lexical(
        all_prose_blocks, int(sentences_dict["count"]), function_words
    )
    voice_dict, typography_dict = extract_voice_and_typography(all_prose_blocks, lexicons)

    per_doc_sentences: list[list[str]] = []
    last_sentences: list[str] = []
    for doc_items in per_doc_parsed:
        doc_sents = [
            sent.text.strip()
            for _blk, sp_doc in doc_items
            for sent in sp_doc.sents
            if sent.text.strip()
        ]
        per_doc_sentences.append(doc_sents)
        if doc_sents:
            last_sentences.append(doc_sents[-1])

    headings_dict, lists_dict, structure_dict = extract_structure_features(
        docs, int(lexical_dict["words"]), last_sentences
    )
    signature_dict, exemplars_dict = extract_signature_and_exemplars(
        per_doc_sentences, function_word_set
    )

    return {
        "sentences": sentences_dict,
        "paragraphs": paragraphs_dict,
        "lexical": lexical_dict,
        "voice": voice_dict,
        "typography": typography_dict,
        "headings": headings_dict,
        "lists": lists_dict,
        "structure": structure_dict,
        "function_word_per_1k": fw_rates,
        "signature": signature_dict,
        "exemplars": exemplars_dict,
    }


def analyze(docs: Sequence[Document], nlp: Any | None = None) -> dict[str, Any]:
    """Extract all 11 linguistic feature groups plus 32-key cross-document stability."""
    active_nlp = nlp if nlp is not None else load_nlp(ner=False)
    lexicons = _default_lexicons()

    # Batch-parse all prose blocks once via nlp.pipe
    flat_blocks: list[tuple[int, Block]] = []
    for doc_idx, doc in enumerate(docs):
        for blk in prose_blocks(doc):
            if blk.text.strip():
                flat_blocks.append((doc_idx, blk))

    per_doc_parsed: list[list[tuple[Block, Any]]] = [[] for _ in docs]
    if flat_blocks:
        texts = [blk.text for _idx, blk in flat_blocks]
        for (doc_idx, blk), sp_doc in zip(flat_blocks, active_nlp.pipe(texts), strict=True):
            per_doc_parsed[doc_idx].append((blk, sp_doc))

    corpus_features = _analyze_core(docs, per_doc_parsed, lexicons)

    if len(docs) <= 1:
        per_doc_features = [corpus_features] if docs else []
    else:
        per_doc_features = [
            _analyze_core([doc], [doc_parsed], lexicons)
            for doc, doc_parsed in zip(docs, per_doc_parsed, strict=True)
        ]

    corpus_features["stability"] = compute_stability(per_doc_features)
    return corpus_features
