"""Voice conformance scorer against an author profile (Rank 3, ADR 0006)."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Any

from casper.documents import prose_blocks
from casper.errors import InputError
from casper.features import analyze
from casper.features.stability import DIMENSION_WEIGHTS, FEATURE_SPECS, extract_path
from casper.layers import extract_pins
from casper.libraries import load_libraries
from casper.models import (
    ConfidenceBand,
    ConformanceReport,
    Document,
    FeatureScore,
    GapItem,
    MatchBand,
)
from casper.parsing import load_nlp

SCALAR_DIMENSIONS: tuple[str, ...] = (
    "rhythm",
    "openers",
    "paragraphs",
    "register",
    "point_of_view",
    "punctuation",
    "rhetoric",
)

_CASE_KEYS: tuple[str, ...] = ("sentence", "title", "upper")
_ALPHA_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
_WS_RE = re.compile(r"\s+")


@lru_cache(maxsize=1)
def _function_words() -> tuple[str, ...]:
    return load_libraries().lexicons["function_words"]


def _normalize_text(text: str) -> str:
    replaced = text.replace("\u2019", "'").replace("\u2018", "'")
    return _WS_RE.sub(" ", replaced.strip()).lower()


def _band_for_score(overall: float) -> MatchBand:
    if overall >= 80.0:
        return MatchBand.STRONG
    if overall >= 65.0:
        return MatchBand.CLOSE
    if overall >= 45.0:
        return MatchBand.PARTIAL
    return MatchBand.DIFFERENT


def _confidence_for_words(word_count: int) -> ConfidenceBand:
    if word_count >= 1000:
        return ConfidenceBand.HIGH
    if word_count >= 250:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.LOW


def _function_words_score(profile: dict[str, Any], cand: dict[str, Any]) -> float:
    raw_prof = profile.get("function_word_per_1k")
    prof_fw: dict[str, Any] = raw_prof if isinstance(raw_prof, dict) else {}
    raw_cand = cand.get("function_word_per_1k")
    cand_fw: dict[str, Any] = raw_cand if isinstance(raw_cand, dict) else {}

    words = _function_words()
    p_vec = [float(prof_fw.get(w, 0.0)) for w in words]
    c_vec = [float(cand_fw.get(w, 0.0)) for w in words]

    norm_p = math.sqrt(sum(v * v for v in p_vec))
    norm_c = math.sqrt(sum(v * v for v in c_vec))
    if norm_p <= 0.0 or norm_c <= 0.0:
        cos = 0.0
    else:
        dot = sum(a * b for a, b in zip(p_vec, c_vec, strict=True))
        cos = dot / (norm_p * norm_c)

    return min(1.0, max(0.0, (cos - 0.85) / (0.97 - 0.85)))


def _structure_score(
    prof_headings: dict[str, Any],
    cand_headings: dict[str, Any],
    widen: float,
) -> float:
    prof_density = float(prof_headings.get("density_per_1k", 0.0))
    cand_density = float(cand_headings.get("density_per_1k", 0.0))
    density_sigma = max(1.5, 0.25 * prof_density) * widen
    density_z = abs(cand_density - prof_density) / density_sigma
    density_score = math.exp(-(density_z**2) / 4.5)

    raw_prof_shares = prof_headings.get("case_shares")
    prof_shares: dict[str, Any] = raw_prof_shares if isinstance(raw_prof_shares, dict) else {}
    raw_cand_shares = cand_headings.get("case_shares")
    cand_shares: dict[str, Any] = raw_cand_shares if isinstance(raw_cand_shares, dict) else {}

    l1_diff = sum(
        abs(float(cand_shares.get(k, 0.0)) - float(prof_shares.get(k, 0.0))) for k in _CASE_KEYS
    )
    case_score = min(1.0, max(0.0, 1.0 - 0.5 * l1_diff))
    return 0.5 * (density_score + case_score)


def _find_signature_matches(profile: dict[str, Any], document: Document) -> tuple[str, ...]:
    sig = profile.get("signature")
    if not isinstance(sig, dict):
        return ()

    candidates: list[str] = []
    for key in ("recurring_phrases", "bounded_phrases"):
        raw_list = sig.get(key)
        if isinstance(raw_list, list):
            candidates.extend(item for item in raw_list if isinstance(item, str) and item.strip())

    if not candidates:
        return ()

    norm_prose = _normalize_text(" ".join(blk.text for blk in prose_blocks(document) if blk.text))
    matched: set[str] = set()
    for phrase in candidates:
        norm_phrase = _normalize_text(phrase)
        pattern = rf"(?<![a-z0-9']){re.escape(norm_phrase)}(?![a-z0-9'])"
        if re.search(pattern, norm_prose):
            matched.add(phrase)
    return tuple(sorted(matched))


def _find_frame_matches(
    profile: dict[str, Any],
    document: Document,
    nlp: Any,
) -> tuple[str, ...]:
    sig = profile.get("signature")
    if not isinstance(sig, dict):
        return ()

    raw_frames = sig.get("sentence_frames")
    if not isinstance(raw_frames, list):
        return ()

    frames = [item for item in raw_frames if isinstance(item, str) and item.strip()]
    if not frames:
        return ()

    texts = [blk.text for blk in prose_blocks(document) if blk.text.strip()]
    sent_norms: list[tuple[str, list[str]]] = [
        (norm_sent, _ALPHA_WORD_RE.findall(norm_sent))
        for sp_doc in nlp.pipe(texts)
        for sent in sp_doc.sents
        if (norm_sent := _normalize_text(sent.text))
    ]

    matched: set[str] = set()
    for frame in frames:
        prefix = frame.strip()
        while prefix.endswith(("...", "\u2026")):
            prefix = prefix[:-3] if prefix.endswith("...") else prefix[:-1]
            prefix = prefix.strip()
        norm_prefix = _normalize_text(prefix)
        if not norm_prefix:
            continue
        prefix_words = _ALPHA_WORD_RE.findall(norm_prefix)
        for norm_sent, sent_words in sent_norms:
            if (
                prefix_words and sent_words[: len(prefix_words)] == prefix_words
            ) or (not prefix_words and norm_sent.startswith(norm_prefix)):
                matched.add(frame)
                break
    return tuple(sorted(matched))


def score(
    profile: dict[str, Any],
    document: Document,
    *,
    nlp: Any | None = None,
) -> ConformanceReport:
    """Score how closely `document` matches an author `profile` (0..100)."""
    active_nlp = nlp if nlp is not None else load_nlp(ner=False)
    cand = analyze([document], nlp=active_nlp)

    candidate_words = int(cand["lexical"]["words"])
    candidate_sentences = int(cand["sentences"]["count"])
    if candidate_words < 1 or candidate_sentences < 1:
        raise InputError("Candidate text has no scorable prose")

    corpus_block = profile.get("corpus")
    raw_avg = corpus_block.get("avg_doc_words") if isinstance(corpus_block, dict) else None
    avg_doc_words = (
        float(raw_avg)
        if isinstance(raw_avg, (int, float)) and not isinstance(raw_avg, bool) and raw_avg > 0
        else 500.0
    )
    widen = min(1.5, max(1.0, math.sqrt(avg_doc_words / max(candidate_words, 1))))

    pins = extract_pins(profile)
    raw_stability = profile.get("stability")
    stability_map: dict[str, Any] = raw_stability if isinstance(raw_stability, dict) else {}

    feature_scores: list[FeatureScore] = []
    dim_weighted_sum: dict[str, float] = {d: 0.0 for d in SCALAR_DIMENSIONS}
    dim_weight_total: dict[str, float] = {d: 0.0 for d in SCALAR_DIMENSIONS}

    for spec in FEATURE_SPECS:
        key = spec.key
        is_pinned = key in pins
        author_val = (
            pins[key]["value"] if is_pinned else float(extract_path(profile, spec.profile_path))
        )
        stab_entry = stability_map.get(key)
        prof_stdev = (
            float(stab_entry.get("stdev", 0.0)) if isinstance(stab_entry, dict) else 0.0
        )
        raw_stdev = pins[key]["stdev"] if (is_pinned and "stdev" in pins[key]) else prof_stdev
        sigma = max(raw_stdev, spec.floor, 0.1 * abs(author_val)) * widen
        cand_val = float(extract_path(cand, spec.profile_path))
        z = abs(cand_val - author_val) / sigma
        f_score = math.exp(-(z**2) / 4.5)

        fs = FeatureScore(
            name=key,
            dimension=spec.dimension,
            author_value=author_val,
            candidate_value=cand_val,
            sigma=sigma,
            z=z,
            score=f_score,
            pinned=is_pinned,
        )
        feature_scores.append(fs)
        dim_weighted_sum[spec.dimension] += spec.weight * f_score
        dim_weight_total[spec.dimension] += spec.weight

    dimensions: dict[str, float] = {
        dim: dim_weighted_sum[dim] / dim_weight_total[dim] for dim in SCALAR_DIMENSIONS
    }
    dimensions["function_words"] = _function_words_score(profile, cand)

    raw_prof_headings = profile.get("headings")
    prof_headings: dict[str, Any] = (
        raw_prof_headings if isinstance(raw_prof_headings, dict) else {}
    )
    cand_headings = cand["headings"]
    if int(cand_headings.get("count", 0)) >= 2 and int(prof_headings.get("count", 0)) > 0:
        dimensions["structure"] = _structure_score(prof_headings, cand_headings, widen)

    weight_sum = sum(DIMENSION_WEIGHTS[d] for d in dimensions)
    log_sum = sum(DIMENSION_WEIGHTS[d] * math.log(max(dimensions[d], 0.02)) for d in dimensions)
    overall = min(100.0, max(0.0, 100.0 * math.exp(log_sum / weight_sum)))

    gap_candidates = sorted(
        (fs for fs in feature_scores if fs.score < 0.5),
        key=lambda fs: (fs.score, fs.name),
    )[:6]
    largest_gaps = tuple(
        GapItem(
            feature=fs.name,
            dimension=fs.dimension,
            score=fs.score,
            author_value=fs.author_value,
            candidate_value=fs.candidate_value,
            sigma=fs.sigma,
            explanation=(
                f"{fs.name} is {'higher' if fs.candidate_value > fs.author_value else 'lower'} "
                f"than author target ({fs.candidate_value:.2f} vs {fs.author_value:.2f}, "
                f"z={fs.z:.2f})"
            ),
        )
        for fs in gap_candidates
    )

    signature_matches = _find_signature_matches(profile, document)
    frame_matches = _find_frame_matches(profile, document, active_nlp)

    return ConformanceReport(
        overall=overall,
        band=_band_for_score(overall),
        confidence=_confidence_for_words(candidate_words),
        word_count=candidate_words,
        dimensions=dimensions,
        features=tuple(feature_scores),
        largest_gaps=largest_gaps,
        signature_matches=signature_matches,
        frame_matches=frame_matches,
    )
