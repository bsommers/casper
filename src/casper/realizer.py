"""Deterministic rule-based realizer, glossary substitution, and limit fitting (Rank 5)."""

from __future__ import annotations

import math
import random
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from casper.conformance import score as score_voice
from casper.errors import InputError
from casper.modalities import count_rendered, format_draft
from casper.models import (
    AdaptedPlan,
    BackendKind,
    Block,
    BlockKind,
    Constraints,
    Document,
    Draft,
    DraftSection,
    Fact,
    FactKind,
    Libraries,
    Modality,
    RewriteRule,
    Sentence,
)
from casper.parsing import load_nlp
from casper.rewrites import (
    REWRITE_RULES,
    TOKEN_RE,
    apply_transition_opener_with_names,
    merge_pair_semicolon,
)

MAX_COMBINATIONS = 512


def _match_case(matched: str, replacement: str) -> str:
    """Match ALL CAPS or Initial Cap from `matched` onto `replacement`."""
    if not replacement:
        return replacement
    if matched.isupper():
        return replacement.upper()
    if matched and matched[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def substitute(text: str, mapping: Mapping[str, str]) -> str:
    """Single-pass, whole-word, case-insensitive, case-preserving longest-key-first substitution."""
    if not text or not mapping:
        return text

    non_empty = [(k, v) for k, v in mapping.items() if k]
    if not non_empty:
        return text

    ordered_keys: list[str] = []
    lookup: dict[str, str] = {}
    for key, replacement in sorted(non_empty, key=lambda kv: (-len(kv[0]), kv[0])):
        lowered = key.lower()
        if lowered not in lookup:
            lookup[lowered] = replacement
            ordered_keys.append(key)

    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(k) for k in ordered_keys) + r")(?!\w)",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: _match_case(m.group(0), lookup[m.group(0).lower()]), text)


def _over_limits(
    words: int,
    chars: int,
    max_words: int | None,
    max_chars: int | None,
) -> bool:
    return (max_words is not None and words > max_words) or (
        max_chars is not None and chars > max_chars
    )


def _has_remaining_ask(
    sections: Sequence[DraftSection],
    fact_by_id: Mapping[str, Fact],
) -> bool:
    for section in sections:
        for sent in section.sentences:
            if sent.frame:
                continue
            for fid in sent.fact_ids:
                fact = fact_by_id.get(fid)
                if fact is not None and fact.kind == FactKind.ASK:
                    return True
    return False


def _drop_frame_sentences(sections: list[DraftSection]) -> tuple[list[DraftSection], bool]:
    changed = False
    cleaned: list[DraftSection] = []
    for section in sections:
        kept = tuple(s for s in section.sentences if not s.frame)
        if len(kept) != len(section.sentences):
            changed = True
        if kept:
            cleaned.append(
                DraftSection(name=section.name, heading=section.heading, sentences=kept)
            )
    return cleaned, changed


def _sentence_salience(sent: Sentence, fact_by_id: Mapping[str, Fact]) -> float:
    scores = [fact_by_id[fid].salience for fid in sent.fact_ids if fid in fact_by_id]
    return max(scores) if scores else 1.0


def fit_to_limits(
    draft: Draft,
    adapted_plan: AdaptedPlan,
    constraints: Constraints,
    modality: Modality,
) -> Draft:
    """Trim lowest-salience droppable sentences until rendered word/char limits hold."""
    max_words = constraints.max_words if constraints.max_words is not None else modality.max_words
    max_chars = constraints.max_chars if constraints.max_chars is not None else modality.max_chars

    words, chars = count_rendered(draft, modality)
    if not _over_limits(words, chars, max_words, max_chars):
        return draft

    fact_by_id: dict[str, Fact] = {
        fact.id: fact for ps in adapted_plan.sections for fact in ps.facts
    }
    required_sections: set[str] = {
        sec.name for sec in adapted_plan.structure.sections if sec.required
    } | {ps.section.name for ps in adapted_plan.sections if ps.section.required}

    sections: list[DraftSection] = [sec for sec in draft.sections if sec.sentences]
    dropped_count = 0
    still_over_protected = False

    def _rebuild(cur_sections: list[DraftSection], warnings: tuple[str, ...]) -> Draft:
        return Draft(
            sections=tuple(cur_sections),
            title=draft.title,
            warnings=warnings,
            candidates_considered=draft.candidates_considered,
            backend=draft.backend,
            declared_additions=draft.declared_additions,
            meta=dict(draft.meta),
        )

    current = _rebuild(sections, draft.warnings)
    words, chars = count_rendered(current, modality)

    while _over_limits(words, chars, max_words, max_chars):
        droppable: list[tuple[float, int, int]] = []
        for sec_idx, section in enumerate(sections):
            first_non_frame = next(
                (i for i, sent in enumerate(section.sentences) if not sent.frame),
                None,
            )
            is_required = section.name in required_sections
            for sent_idx, sent in enumerate(section.sentences):
                if sent.frame:
                    continue
                if is_required and sent_idx == first_non_frame:
                    continue
                droppable.append((_sentence_salience(sent, fact_by_id), -sec_idx, -sent_idx))

        if not droppable:
            still_over_protected = True
            break

        _, neg_sec_idx, neg_sent_idx = min(droppable)
        target_sec = -neg_sec_idx
        target_sent = -neg_sent_idx

        old_sec = sections[target_sec]
        new_sents = tuple(
            s for idx, s in enumerate(old_sec.sentences) if idx != target_sent
        )
        if new_sents:
            sections[target_sec] = DraftSection(
                name=old_sec.name,
                heading=old_sec.heading,
                sentences=new_sents,
            )
        else:
            del sections[target_sec]
        dropped_count += 1

        if not _has_remaining_ask(sections, fact_by_id):
            sections, _ = _drop_frame_sentences(sections)

        current = _rebuild(sections, draft.warnings)
        words, chars = count_rendered(current, modality)

    if not _has_remaining_ask(sections, fact_by_id):
        sections, frame_dropped = _drop_frame_sentences(sections)
        if frame_dropped:
            current = _rebuild(sections, draft.warnings)
            words, chars = count_rendered(current, modality)

    warnings = list(draft.warnings)
    if dropped_count > 0:
        warnings.append(
            f"Trimmed {dropped_count} sentence(s) to fit modality/constraint limits."
        )
    if still_over_protected and _over_limits(words, chars, max_words, max_chars):
        warnings.append(
            f"Draft still exceeds limits ({words} words, {chars} chars) "
            "with only protected sentences remaining."
        )

    return _rebuild(sections, tuple(warnings))


@dataclass(frozen=True)
class _FactVariant:
    text: str
    added_tokens: frozenset[str]


@dataclass(frozen=True)
class _Candidate:
    draft: Draft
    rendered: str


class _CachedNlp:
    """Per-realize() text-keyed parse cache wrapping a spaCy Language pipeline."""

    def __init__(self, nlp: Any) -> None:
        self._nlp = nlp
        self._cache: dict[str, Any] = {}

    def __call__(self, text: str) -> Any:
        cached = self._cache.get(text)
        if cached is None:
            cached = self._nlp(text)
            self._cache[text] = cached
        return cached

    def pipe(self, texts: Iterable[str], *args: Any, **kwargs: Any) -> Iterator[Any]:
        text_list = list(texts)
        missing: list[str] = []
        seen_missing: set[str] = set()
        for text in text_list:
            if text not in self._cache and text not in seen_missing:
                missing.append(text)
                seen_missing.add(text)
        if missing:
            for text, sp_doc in zip(
                missing,
                self._nlp.pipe(missing, *args, **kwargs),
                strict=True,
            ):
                self._cache[text] = sp_doc
        for text in text_list:
            yield self._cache[text]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._nlp, name)


def _decode_flat_index(flat_idx: int, bases: Sequence[int]) -> tuple[int, ...]:
    """Decode a flat combination index into per-fact variant indices via modular arithmetic."""
    choices: list[int] = []
    rem = flat_idx
    for base in bases:
        choices.append(rem % base)
        rem //= base
    return tuple(choices)


def _sample_flat_indices(
    bases: Sequence[int],
    seed: int,
    *,
    max_combinations: int = MAX_COMBINATIONS,
) -> list[int]:
    """Return flat indices capped at `max_combinations`, always starting with 0 (all-plain)."""
    if not bases:
        return [0]
    total = math.prod(bases)
    if total <= max_combinations:
        return list(range(total))
    rng = random.Random(seed)
    seen: set[int] = {0}
    sampled: list[int] = [0]
    while len(sampled) < max_combinations:
        candidate = rng.randrange(1, total)
        if candidate not in seen:
            seen.add(candidate)
            sampled.append(candidate)
    return sampled


def _extract_added_tokens(
    base_text: str,
    variant_text: str,
    rule_added_tokens: frozenset[str],
) -> frozenset[str]:
    if not rule_added_tokens:
        return frozenset()
    allowed = frozenset(tok.lower() for tok in rule_added_tokens)
    base_tokens = {tok.lower() for tok in TOKEN_RE.findall(base_text)}
    variant_tokens = {tok.lower() for tok in TOKEN_RE.findall(variant_text)}
    return frozenset((variant_tokens - base_tokens) & allowed)


def _draft_to_document(draft: Draft, modality: Modality) -> Document:
    """Build a Document matching the draft's block structure for voice conformance scoring."""
    blocks: list[Block] = []
    for section in draft.sections:
        if not section.sentences:
            continue
        if modality.headings != "none" and section.heading:
            blocks.append(Block(kind=BlockKind.HEADING, text=section.heading, level=2))
        body_sents = [s for s in section.sentences if not s.frame]
        frame_sents = [s for s in section.sentences if s.frame]
        if body_sents:
            if modality.bullets and len(body_sents) >= 2:
                for sent in body_sents:
                    blocks.append(Block(kind=BlockKind.LIST_ITEM, text=sent.text))
            else:
                blocks.append(
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text=" ".join(sent.text for sent in body_sents),
                    )
                )
        for frame_sent in frame_sents:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=frame_sent.text))
    return Document(
        source="<candidate>",
        format=str(modality.markup),
        title=draft.title if modality.title else None,
        blocks=tuple(blocks),
    )


class RuleBasedRealizer:
    """Deterministic rule-based draft realizer with voice-guided candidate ranking."""

    def __init__(
        self,
        libs: Libraries,
        *,
        rules: Sequence[RewriteRule] = REWRITE_RULES,
    ) -> None:
        self.libs = libs
        self.rules: tuple[RewriteRule, ...] = tuple(rules)

    def _build_fact_variants(
        self,
        fact: Fact,
        fact_idx: int,
        substitutions: Mapping[str, str],
    ) -> list[_FactVariant]:
        base_text = substitute(fact.text, substitutions)
        variants: list[_FactVariant] = [_FactVariant(text=base_text, added_tokens=frozenset())]
        seen_texts: set[str] = {base_text}

        for rule in self.rules:
            if rule.id in {"plain", "semicolon_merge"}:
                continue
            if rule.id == "transition_opener":
                if fact_idx == 0:
                    continue
                protected = (*fact.entities, *fact.owners)
                outputs = apply_transition_opener_with_names(base_text, protected)
            else:
                outputs = rule.apply(base_text)

            for out_text in outputs:
                if out_text and out_text != base_text and out_text not in seen_texts:
                    added = _extract_added_tokens(base_text, out_text, rule.added_tokens)
                    variants.append(_FactVariant(text=out_text, added_tokens=added))
                    seen_texts.add(out_text)

        return variants

    def _select_closing_phrase(
        self,
        adapted_plan: AdaptedPlan,
        constraints: Constraints,
    ) -> str | None:
        if adapted_plan.cta_style is None:
            return None
        phrases = self.libs.phrasebank.get(adapted_plan.cta_style)
        if not phrases:
            return None
        return phrases[constraints.seed % len(phrases)]

    def realize(
        self,
        adapted_plan: AdaptedPlan,
        voice: dict[str, Any] | None,
        constraints: Constraints,
        modality: Modality,
        *,
        nlp: Any | None = None,
    ) -> Draft:
        """Realize an AdaptedPlan into a Draft under constraints and optional voice profile."""
        non_empty_sections = [ps for ps in adapted_plan.sections if ps.facts]
        if not non_empty_sections:
            empty_draft = Draft(
                sections=(),
                warnings=adapted_plan.warnings,
                candidates_considered=1,
                backend=BackendKind.RULES,
                declared_additions=frozenset(),
            )
            return fit_to_limits(empty_draft, adapted_plan, constraints, modality)

        closing_phrase = self._select_closing_phrase(adapted_plan, constraints)
        semicolon_rule = next((r for r in self.rules if r.id == "semicolon_merge"), None)

        # Build per-fact variants across all non-empty sections.
        section_variants: list[list[tuple[Fact, list[_FactVariant]]]] = []
        flat_bases: list[int] = []
        for ps in non_empty_sections:
            sec_list: list[tuple[Fact, list[_FactVariant]]] = []
            for fact_idx, fact in enumerate(ps.facts):
                variants = self._build_fact_variants(fact, fact_idx, adapted_plan.substitutions)
                sec_list.append((fact, variants))
                flat_bases.append(len(variants))
            section_variants.append(sec_list)

        def _assemble_draft(
            choices: tuple[int, ...],
            *,
            apply_semicolon: bool = False,
        ) -> tuple[Draft, bool]:
            draft_sections: list[DraftSection] = []
            added_tokens: set[str] = set()
            merged_any = False
            cursor = 0
            last_sec_idx = len(non_empty_sections) - 1

            for sec_idx, (ps, sec_facts) in enumerate(
                zip(non_empty_sections, section_variants, strict=True)
            ):
                sentences: list[Sentence] = []
                chosen_variants: list[tuple[Fact, _FactVariant]] = []
                for fact, variants in sec_facts:
                    chosen = variants[choices[cursor]]
                    cursor += 1
                    chosen_variants.append((fact, chosen))
                    added_tokens.update(chosen.added_tokens)

                start_idx = 0
                if apply_semicolon and len(chosen_variants) >= 2:
                    f1, v1 = chosen_variants[0]
                    f2, v2 = chosen_variants[1]
                    merged = merge_pair_semicolon(
                        v1.text,
                        v2.text,
                        protected_names=(*f2.entities, *f2.owners),
                    )
                    if merged is not None:
                        sentences.append(
                            Sentence(text=merged, fact_ids=(f1.id, f2.id), frame=False)
                        )
                        if semicolon_rule is not None and semicolon_rule.added_tokens:
                            added_tokens.update(
                                _extract_added_tokens(
                                    f"{v1.text} {v2.text}",
                                    merged,
                                    semicolon_rule.added_tokens,
                                )
                            )
                        merged_any = True
                        start_idx = 2

                for fact, chosen in chosen_variants[start_idx:]:
                    sentences.append(Sentence(text=chosen.text, fact_ids=(fact.id,), frame=False))

                if sec_idx == last_sec_idx and closing_phrase is not None:
                    sentences.append(Sentence(text=closing_phrase, fact_ids=(), frame=True))

                draft_sections.append(
                    DraftSection(
                        name=ps.section.name,
                        heading=ps.section.heading,
                        sentences=tuple(sentences),
                    )
                )

            candidate_draft = Draft(
                sections=tuple(draft_sections),
                warnings=adapted_plan.warnings,
                candidates_considered=1,
                backend=BackendKind.RULES,
                declared_additions=frozenset(added_tokens),
            )
            return candidate_draft, merged_any

        # Direct-index OOM-safe sampling (never materializes itertools.product).
        flat_indices = _sample_flat_indices(
            flat_bases,
            constraints.seed,
            max_combinations=MAX_COMBINATIONS,
        )

        # Fast path when voice is None: pick all-plain candidate 0 without invoking spaCy.
        if voice is None:
            plain_choices = _decode_flat_index(0, flat_bases)
            plain_draft, _ = _assemble_draft(plain_choices, apply_semicolon=False)
            return fit_to_limits(plain_draft, adapted_plan, constraints, modality)

        # Build deduplicated candidate pool (always anchored by index 0 all-plain).
        unique_candidates: list[_Candidate] = []
        seen_rendered: set[str] = set()

        def _add_candidate(cand_draft: Draft) -> bool:
            rendered = format_draft(cand_draft, modality)
            if rendered in seen_rendered:
                return False
            seen_rendered.add(rendered)
            unique_candidates.append(_Candidate(draft=cand_draft, rendered=rendered))
            return True

        plain_choices = _decode_flat_index(0, flat_bases)
        plain_draft, _ = _assemble_draft(plain_choices, apply_semicolon=False)
        _add_candidate(plain_draft)

        has_semicolon_candidate = False
        if semicolon_rule is not None:
            merged_draft, merged_any = _assemble_draft(plain_choices, apply_semicolon=True)
            if merged_any:
                has_semicolon_candidate = _add_candidate(merged_draft)

        for flat_idx in flat_indices[1:]:
            if len(unique_candidates) >= MAX_COMBINATIONS:
                break
            choices = _decode_flat_index(flat_idx, flat_bases)
            cand_draft, _ = _assemble_draft(choices, apply_semicolon=False)
            _add_candidate(cand_draft)

        # Cap evaluated candidates deterministically using constraints.candidates and seed.
        cap = min(max(1, constraints.candidates), MAX_COMBINATIONS)
        if len(unique_candidates) <= cap:
            selected = unique_candidates
        else:
            pinned_count = 2 if (has_semicolon_candidate and cap >= 2) else 1
            pinned = unique_candidates[:pinned_count]
            rest = unique_candidates[pinned_count:]
            rng_select = random.Random(constraints.seed)
            sampled_rest = rng_select.sample(rest, cap - pinned_count)
            selected = [*pinned, *sampled_rest]

        # Score unique candidates with a per-call text-keyed spaCy parse cache.
        active_nlp = _CachedNlp(nlp if nlp is not None else load_nlp(ner=False))
        best_idx = 0
        best_score = -1.0
        for idx, cand in enumerate(selected):
            doc = _draft_to_document(cand.draft, modality)
            try:
                report = score_voice(voice, doc, nlp=active_nlp)
                cand_score = report.overall
            except InputError:
                cand_score = -1.0
            if idx == 0 or cand_score > best_score:
                best_score = cand_score
                best_idx = idx

        winner = selected[best_idx].draft
        final_draft = Draft(
            sections=winner.sections,
            title=winner.title,
            warnings=winner.warnings,
            candidates_considered=len(selected),
            backend=BackendKind.RULES,
            declared_additions=winner.declared_additions,
            meta=dict(winner.meta),
        )
        return fit_to_limits(final_draft, adapted_plan, constraints, modality)
