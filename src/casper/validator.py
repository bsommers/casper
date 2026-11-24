"""Strict & assisted fidelity, persona, limit, and voice validator (Rank 5).

Enforces zero-invention traceability in STRICT mode and anti-hallucination guards
in ASSISTED mode without ever importing `realizer` or `llm` (ADR 0012).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from casper import conformance
from casper.errors import InputError
from casper.modalities import count_rendered
from casper.models import (
    DEPTH_CAPS,
    AdaptedPlan,
    Block,
    BlockKind,
    CheckFinding,
    CheckLevel,
    ConfidenceBand,
    ConformanceReport,
    Constraints,
    Document,
    Draft,
    Fact,
    FactModel,
    FidelityMode,
    Glossary,
    JargonLevel,
    Modality,
    Validation,
)
from casper.parsing import load_nlp
from casper.rewrites import ALLOWED_RULE_TOKENS, TOKEN_RE

NUMBER_RE = re.compile(r"[+-]?\d+(?:[.,]\d+)*%?")
_THOUSANDS_COMMA_RE = re.compile(r",(?=\d{3}(?:\D|$))")
_NAME_SCAN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_MID_NAME_RE = re.compile(r"^[A-Z][a-zA-Z0-9_-]+$")
_BENIGN_NEGATION_IDIOMS_RE = re.compile(
    r"(?<!\w)(?:not\s+only|no\s+later\s+than|no\s+issues|zero\s+issues)(?!\w)",
    re.IGNORECASE,
)

# Closed stop-word list (spec/01-data-model.md §6.4) always permitted as syntactic glue.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "that",
        "this",
        "these",
        "those",
        "with",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "after",
        "before",
        "between",
        "through",
        "during",
        "while",
        "where",
        "when",
        "which",
        "whose",
        "whom",
        "their",
        "there",
        "they",
        "them",
        "have",
        "been",
        "being",
        "were",
        "will",
        "would",
        "could",
        "should",
        "shall",
        "must",
        "does",
        "done",
        "each",
        "both",
        "more",
        "most",
        "some",
        "such",
        "than",
        "then",
        "also",
        "only",
        "very",
        "just",
        "your",
        "ours",
        "status",
        "owner",
        "risk",
        "blocker",
        "next",
        "step",
        "decision",
        "progress",
        "background",
        "metric",
        "request",
    }
)

NEGATION_TOKENS: frozenset[str] = frozenset(
    {
        "no",
        "not",
        "never",
        "none",
        "nobody",
        "nothing",
        "neither",
        "nowhere",
        "cannot",
        "can't",
        "won't",
        "don't",
        "doesn't",
        "didn't",
        "isn't",
        "aren't",
        "wasn't",
        "weren't",
        "hasn't",
        "haven't",
        "hadn't",
        "wouldn't",
        "couldn't",
        "shouldn't",
        "without",
        "failed",
        "unable",
    }
)

ANTONYM_PAIRS: tuple[tuple[str, str], ...] = (
    ("approved", "rejected"),
    ("on track", "blocked"),
    ("passed", "failed"),
    ("increased", "decreased"),
    ("slipped", "ahead"),
    ("enabled", "disabled"),
    ("delayed", "accelerated"),
    ("added", "removed"),
)

_PERSONA_CHECK_CODES: tuple[str, ...] = (
    "persona-avoid",
    "persona-jargon",
    "persona-depth",
    "persona-order",
)


def _normalize_quotes(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'")


def _whole_word_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def _contains_term(text: str, term: str) -> bool:
    if not term.strip():
        return False
    return _whole_word_pattern(term.strip()).search(text) is not None


def _tokenize_lower(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_RE.findall(_normalize_quotes(text))]


def _normalize_number(raw: str) -> str:
    return _THOUSANDS_COMMA_RE.sub("", raw)


def _extract_numbers(text: str) -> list[str]:
    return [_normalize_number(m.group(0)) for m in NUMBER_RE.finditer(text)]


def _count_negations(text: str) -> int:
    norm = _normalize_quotes(text)
    stripped = _BENIGN_NEGATION_IDIOMS_RE.sub(" ", norm)
    return sum(1 for tok in TOKEN_RE.findall(stripped) if tok.lower() in NEGATION_TOKENS)


def _collect_name_tokens(texts: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        norm = _normalize_quotes(text)
        for tok in _NAME_SCAN_RE.findall(norm):
            tokens.add(tok.lower())
        for tok in TOKEN_RE.findall(norm):
            tokens.add(tok.lower())
    return tokens


def _has_internal_cap(token: str) -> bool:
    return any(ch.isupper() for ch in token[1:])


def _is_all_caps_acronym(token: str) -> bool:
    return len(token) >= 2 and token.isupper()


def _is_spacy_propn(text: str, match: re.Match[str], nlp: Any) -> bool:
    sp_doc = nlp(text)
    start, end = match.start(), match.end()
    for sp_tok in sp_doc:
        tok_start = sp_tok.idx
        tok_end = tok_start + len(sp_tok.text)
        if tok_end <= start:
            continue
        if tok_start >= end:
            break
        if sp_tok.pos_ == "PROPN":
            return True
    return False


def _check_assisted_names(
    sentence_text: str,
    cited_facts: list[Fact],
    replacement_names: set[str],
    declared_lower: frozenset[str],
    get_nlp: Any,
) -> list[str]:
    """Return unsupported proper names found in `sentence_text` (including index 0)."""
    norm = _normalize_quotes(sentence_text)
    matches = list(_NAME_SCAN_RE.finditer(norm))
    if not matches:
        return []

    permitted_names: set[str] = set(replacement_names)
    permitted_names.update(declared_lower)
    permitted_names.update(ALLOWED_RULE_TOKENS)
    for fact in cited_facts:
        permitted_names.update(_collect_name_tokens((fact.text, *fact.entities, *fact.owners)))

    unsupported: list[str] = []
    seen_lower: set[str] = set()

    for idx, match in enumerate(matches):
        tok = match.group(0)
        low = tok.lower()
        if len(tok) < 2 or low in permitted_names or low in seen_lower:
            continue

        if idx > 0:
            if _MID_NAME_RE.match(tok) or _has_internal_cap(tok):
                unsupported.append(tok)
                seen_lower.add(low)
        else:
            if low in STOP_WORDS:
                continue
            if _has_internal_cap(tok) or _is_all_caps_acronym(tok):
                unsupported.append(tok)
                seen_lower.add(low)
            elif tok[0].isupper() and _is_spacy_propn(norm, match, get_nlp()):
                unsupported.append(tok)
                seen_lower.add(low)

    return unsupported


def _check_polarity_mismatch(sentence_text: str, cited_facts: list[Fact]) -> str | None:
    """Return mismatch reason if sentence flips polarity vs. cited facts, else None."""
    sent_neg = _count_negations(sentence_text)
    fact_negs = [_count_negations(f.text) for f in cited_facts]

    if len(cited_facts) == 1:
        if (sent_neg % 2) != (fact_negs[0] % 2):
            return (
                f"Negation parity mismatch against {cited_facts[0].id} "
                f"(sentence={sent_neg}, fact={fact_negs[0]})."
            )
    else:
        fact_has_neg = [n > 0 for n in fact_negs]
        sent_has_neg = sent_neg > 0
        if all(fact_has_neg) and not sent_has_neg:
            return "Affirmative sentence disagrees with all negated cited facts."
        if not any(fact_has_neg) and sent_has_neg:
            return "Negated sentence disagrees with all affirmative cited facts."

    cited_combined = "\n".join(f.text for f in cited_facts)
    for term_a, term_b in ANTONYM_PAIRS:
        for src_term, opp_term in ((term_a, term_b), (term_b, term_a)):
            if (
                _contains_term(cited_combined, src_term)
                and _contains_term(sentence_text, opp_term)
                and not _contains_term(cited_combined, opp_term)
            ):
                return (
                    f"Antonym polarity flip: introduced '{opp_term}' while cited facts "
                    f"state '{src_term}'."
                )

    return None


def _draft_to_document(draft: Draft, modality: Modality) -> Document:
    """Convert a Draft into a Document preserving headings and paragraph blocks."""
    blocks: list[Block] = []
    for sec in draft.sections:
        non_empty = [s for s in sec.sentences if s.text.strip()]
        if not non_empty:
            continue
        if sec.heading and modality.headings != "none":
            blocks.append(Block(kind=BlockKind.HEADING, text=sec.heading, level=2))
        body_texts = [s.text.strip() for s in non_empty if not s.frame]
        frame_texts = [s.text.strip() for s in non_empty if s.frame]
        if body_texts:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=" ".join(body_texts)))
        for frame_text in frame_texts:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=frame_text))
    return Document(
        source="<draft>",
        format=modality.markup.value,
        title=draft.title,
        blocks=tuple(blocks),
    )


def _check_term_matches(
    draft: Draft,
    terms: Iterable[tuple[str, str]],
    *,
    code: str,
    level: CheckLevel,
    findings: list[CheckFinding],
) -> None:
    """Check title and all sentences for whole-word matches of `(term, message_suffix)`."""
    term_patterns = [
        (term, suffix, _whole_word_pattern(term)) for term, suffix in terms if term.strip()
    ]
    if not term_patterns:
        return

    if draft.title and draft.title.strip():
        for term, suffix, pattern in term_patterns:
            if pattern.search(draft.title):
                findings.append(
                    CheckFinding(
                        code=code,
                        level=level,
                        message=f"{suffix} ('{term}') in draft title.",
                    )
                )

    for sec in draft.sections:
        for idx, sent in enumerate(sec.sentences):
            if not sent.text.strip():
                continue
            for term, suffix, pattern in term_patterns:
                if pattern.search(sent.text):
                    findings.append(
                        CheckFinding(
                            code=code,
                            level=level,
                            message=f"{suffix} ('{term}') in section '{sec.name}'.",
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )


def validate(
    draft: Draft,
    adapted_plan: AdaptedPlan,
    fact_model: FactModel,
    voice: dict[str, Any] | None,
    constraints: Constraints,
    modality: Modality,
    *,
    fidelity_mode: FidelityMode,
    glossary: Glossary,
    nlp: Any | None = None,
) -> Validation:
    """Validate draft fidelity, limits, terminology, persona alignment, plan, and voice."""
    findings: list[CheckFinding] = []
    fact_by_id: dict[str, Fact] = {f.id: f for f in fact_model.facts}

    cached_nlp: list[Any] = [nlp]

    def _get_nlp() -> Any:
        if cached_nlp[0] is None:
            cached_nlp[0] = load_nlp(ner=False)
        return cached_nlp[0]

    non_empty_sentences = [
        (sec, idx, sent)
        for sec in draft.sections
        for idx, sent in enumerate(sec.sentences)
        if sent.text.strip()
    ]
    is_empty = len(non_empty_sentences) == 0
    if is_empty:
        findings.append(
            CheckFinding(
                code="empty",
                level=CheckLevel.ERROR,
                message="Draft contains no non-empty sentences.",
            )
        )

    declared_lower = frozenset(tok.lower() for tok in draft.declared_additions)
    if fidelity_mode == FidelityMode.STRICT:
        invalid_declared = sorted(declared_lower - ALLOWED_RULE_TOKENS)
        if invalid_declared:
            findings.append(
                CheckFinding(
                    code="undeclared-addition",
                    level=CheckLevel.ERROR,
                    message=(
                        "Draft.declared_additions contains unregistered rule token(s): "
                        f"{', '.join(invalid_declared)}."
                    ),
                )
            )

    replacement_tokens: frozenset[str] = frozenset(
        tok for val in adapted_plan.substitutions.values() for tok in _tokenize_lower(val)
    )
    replacement_names: set[str] = _collect_name_tokens(adapted_plan.substitutions.values())

    # Sentence-level traceability and fidelity checks.
    for sec in draft.sections:
        for idx, sent in enumerate(sec.sentences):
            if sent.frame:
                if sent.fact_ids:
                    findings.append(
                        CheckFinding(
                            code="frame-with-facts",
                            level=CheckLevel.ERROR,
                            message=(
                                f"Frame sentence in section '{sec.name}' must not cite facts "
                                f"({', '.join(sent.fact_ids)})."
                            ),
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )
                continue

            if not sent.text.strip():
                continue

            if not sent.fact_ids:
                findings.append(
                    CheckFinding(
                        code="untraced",
                        level=CheckLevel.ERROR,
                        message=f"Non-frame sentence in section '{sec.name}' cites no facts.",
                        section=sec.name,
                        sentence_index=idx,
                    )
                )
                continue

            unknown_ids = [fid for fid in sent.fact_ids if fid not in fact_by_id]
            for fid in unknown_ids:
                findings.append(
                    CheckFinding(
                        code="unknown-fact",
                        level=CheckLevel.ERROR,
                        message=f"Sentence references unknown fact id '{fid}'.",
                        section=sec.name,
                        sentence_index=idx,
                    )
                )

            cited_facts = [fact_by_id[fid] for fid in sent.fact_ids if fid in fact_by_id]
            if not cited_facts:
                continue

            # Signed numeric fidelity check (both STRICT and ASSISTED).
            cited_numbers: set[str] = set()
            for fact in cited_facts:
                cited_numbers.update(_extract_numbers(fact.text))

            bad_numbers: list[str] = []
            for num in _extract_numbers(sent.text):
                if num not in cited_numbers and num not in bad_numbers:
                    bad_numbers.append(num)
            if bad_numbers:
                findings.append(
                    CheckFinding(
                        code="unsupported-number",
                        level=CheckLevel.ERROR,
                        message=(
                            f"Unsupported number(s) {', '.join(bad_numbers)} not present in "
                            f"cited facts ({', '.join(f.id for f in cited_facts)})."
                        ),
                        section=sec.name,
                        sentence_index=idx,
                    )
                )

            cited_tokens: set[str] = set()
            for fact in cited_facts:
                cited_tokens.update(_tokenize_lower(fact.text))

            sent_tokens = _tokenize_lower(sent.text)

            if fidelity_mode == FidelityMode.STRICT:
                undeclared_rule_toks: list[str] = []
                unsupported_claim_toks: list[str] = []
                for tok in sent_tokens:
                    if tok in cited_tokens or tok in replacement_tokens or tok in STOP_WORDS:
                        continue
                    if len(tok) <= 3 and "'" not in tok and tok not in NEGATION_TOKENS:
                        continue
                    if tok in declared_lower and tok in ALLOWED_RULE_TOKENS:
                        continue
                    if tok in ALLOWED_RULE_TOKENS:
                        if tok not in undeclared_rule_toks:
                            undeclared_rule_toks.append(tok)
                    elif tok not in unsupported_claim_toks:
                        unsupported_claim_toks.append(tok)

                if undeclared_rule_toks:
                    findings.append(
                        CheckFinding(
                            code="undeclared-addition",
                            level=CheckLevel.ERROR,
                            message=(
                                "Rule token(s) used without declaration in "
                                f"Draft.declared_additions: {', '.join(undeclared_rule_toks)}."
                            ),
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )
                if unsupported_claim_toks:
                    findings.append(
                        CheckFinding(
                            code="unsupported-claim",
                            level=CheckLevel.ERROR,
                            message=(
                                "Unsupported token(s) introduced in strict mode: "
                                f"{', '.join(unsupported_claim_toks)}."
                            ),
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )
            else:
                # ASSISTED mode: reworded (WARNING), unsupported-name (ERROR), polarity-mismatch (ERROR).
                reworded_toks: list[str] = []
                for tok in sent_tokens:
                    if len(tok) <= 3:
                        continue
                    if (
                        tok in cited_tokens
                        or tok in replacement_tokens
                        or tok in STOP_WORDS
                        or tok in ALLOWED_RULE_TOKENS
                    ):
                        continue
                    if tok not in reworded_toks:
                        reworded_toks.append(tok)
                if reworded_toks:
                    findings.append(
                        CheckFinding(
                            code="reworded",
                            level=CheckLevel.WARNING,
                            message=(
                                "Assisted draft introduced reworded content token(s): "
                                f"{', '.join(reworded_toks)}."
                            ),
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )

                bad_names = _check_assisted_names(
                    sent.text,
                    cited_facts,
                    replacement_names,
                    declared_lower,
                    _get_nlp,
                )
                if bad_names:
                    findings.append(
                        CheckFinding(
                            code="unsupported-name",
                            level=CheckLevel.ERROR,
                            message=(
                                f"Unsupported proper name(s) {', '.join(bad_names)} not present "
                                f"in cited facts ({', '.join(f.id for f in cited_facts)})."
                            ),
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )

                polarity_reason = _check_polarity_mismatch(sent.text, cited_facts)
                if polarity_reason is not None:
                    findings.append(
                        CheckFinding(
                            code="polarity-mismatch",
                            level=CheckLevel.ERROR,
                            message=polarity_reason,
                            section=sec.name,
                            sentence_index=idx,
                        )
                    )

    # Rendered length limits (count_rendered).
    word_count, char_count = count_rendered(draft, modality)
    max_words = constraints.max_words if constraints.max_words is not None else modality.max_words
    max_chars = constraints.max_chars if constraints.max_chars is not None else modality.max_chars

    if max_words is not None and word_count > max_words:
        findings.append(
            CheckFinding(
                code="too-long",
                level=CheckLevel.ERROR,
                message=f"Rendered draft has {word_count} words, exceeding limit of {max_words}.",
            )
        )
    if max_chars is not None and char_count > max_chars:
        findings.append(
            CheckFinding(
                code="too-long-chars",
                level=CheckLevel.ERROR,
                message=(
                    f"Rendered draft has {char_count} characters, exceeding limit of {max_chars}."
                ),
            )
        )

    # Banned terms (ERROR) across all sentences and Draft.title.
    banned_terms = sorted(
        {term.strip() for term in (*glossary.banned, *constraints.banned) if term.strip()},
        key=str.lower,
    )
    _check_term_matches(
        draft,
        [(term, "Banned term found") for term in banned_terms],
        code="banned-term",
        level=CheckLevel.ERROR,
        findings=findings,
    )

    # Leftover preferred glossary keys (WARNING) across all sentences and Draft.title.
    preferred_terms = sorted(glossary.preferred.items(), key=lambda kv: kv[0].lower())
    _check_term_matches(
        draft,
        [(src, f"Discouraged glossary term found; prefer '{dst}'") for src, dst in preferred_terms],
        code="glossary",
        level=CheckLevel.WARNING,
        findings=findings,
    )

    # Persona alignment checks (4 categories contributing to persona_score).
    avoid_terms = sorted(
        {term.strip() for term in adapted_plan.target.vocabulary_avoid if term.strip()},
        key=str.lower,
    )
    _check_term_matches(
        draft,
        [
            (term, f"Term avoided by target persona '{adapted_plan.target.id}'")
            for term in avoid_terms
        ],
        code="persona-avoid",
        level=CheckLevel.WARNING,
        findings=findings,
    )

    if adapted_plan.target.jargon_level == JargonLevel.LOW:
        plain_terms = sorted(glossary.plain.items(), key=lambda kv: kv[0].lower())
        _check_term_matches(
            draft,
            [
                (
                    jargon,
                    f"Jargon term found for low-jargon target '{adapted_plan.target.id}'; "
                    f"prefer '{plain_rep}'",
                )
                for jargon, plain_rep in plain_terms
            ],
            code="persona-jargon",
            level=CheckLevel.WARNING,
            findings=findings,
        )

    depth_cap = DEPTH_CAPS[adapted_plan.target.detail_depth]
    for sec in draft.sections:
        non_frame_count = sum(1 for s in sec.sentences if not s.frame and s.text.strip())
        if non_frame_count > depth_cap:
            findings.append(
                CheckFinding(
                    code="persona-depth",
                    level=CheckLevel.WARNING,
                    message=(
                        f"Section '{sec.name}' has {non_frame_count} non-frame sentences, "
                        f"exceeding {adapted_plan.target.detail_depth.value} depth cap of "
                        f"{depth_cap}."
                    ),
                    section=sec.name,
                )
            )

    non_empty_section_names = [
        sec.name for sec in draft.sections if any(s.text.strip() for s in sec.sentences)
    ]
    priority_index = {name: idx for idx, name in enumerate(adapted_plan.target.section_priority)}
    section_ranks = [
        priority_index.get(name, len(priority_index)) for name in non_empty_section_names
    ]
    if section_ranks != sorted(section_ranks):
        findings.append(
            CheckFinding(
                code="persona-order",
                level=CheckLevel.WARNING,
                message=(
                    f"Draft section order {non_empty_section_names} does not follow target "
                    f"priority {list(adapted_plan.target.section_priority)}."
                ),
            )
        )

    # Plan completeness check (required sections & missing required section plan warnings).
    non_empty_name_set = set(non_empty_section_names)
    flagged_required: set[str] = set()
    for sec_spec in adapted_plan.structure.sections:
        if sec_spec.required and sec_spec.name not in non_empty_name_set:
            flagged_required.add(sec_spec.name)
            findings.append(
                CheckFinding(
                    code="plan",
                    level=CheckLevel.WARNING,
                    message=f"Required section '{sec_spec.name}' is missing or empty in draft.",
                    section=sec_spec.name,
                )
            )
    for warn in adapted_plan.warnings:
        lower_warn = warn.lower()
        if "required section" in lower_warn:
            if not any(f"'{name.lower()}'" in lower_warn for name in flagged_required):
                findings.append(
                    CheckFinding(
                        code="plan",
                        level=CheckLevel.WARNING,
                        message=warn,
                    )
                )

    # Voice conformance check (when voice profile is provided and draft is non-empty).
    voice_report: ConformanceReport | None = None
    if voice is not None and not is_empty:
        doc = _draft_to_document(draft, modality)
        try:
            voice_report = conformance.score(voice, doc, nlp=_get_nlp())
        except InputError as exc:
            findings.append(
                CheckFinding(
                    code="voice-unscorable",
                    level=CheckLevel.WARNING,
                    message=f"Draft could not be scored for voice conformance: {exc}",
                )
            )
            voice_report = None
        else:
            if voice_report.confidence == ConfidenceBand.LOW:
                findings.append(
                    CheckFinding(
                        code="voice-low-confidence",
                        level=CheckLevel.WARNING,
                        message=(
                            f"Voice conformance confidence is low ({voice_report.word_count} "
                            "words; >=250 recommended)."
                        ),
                    )
                )
            if constraints.min_voice is not None and voice_report.overall < constraints.min_voice:
                findings.append(
                    CheckFinding(
                        code="voice-below-threshold",
                        level=CheckLevel.ERROR,
                        message=(
                            f"Voice conformance score {voice_report.overall:.1f} is below "
                            f"minimum threshold {constraints.min_voice:.1f}."
                        ),
                    )
                )

    finding_codes = {f.code for f in findings}
    passed_persona = sum(1 for code in _PERSONA_CHECK_CODES if code not in finding_codes)
    persona_score = (passed_persona / 4.0) * 100.0
    ok = not any(f.level == CheckLevel.ERROR for f in findings)

    return Validation(
        ok=ok,
        findings=tuple(findings),
        persona_score=persona_score,
        voice_report=voice_report,
        fidelity_mode=fidelity_mode,
    )
