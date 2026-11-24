"""Structure planning and persona adaptation (Rank 4)."""

from __future__ import annotations

import re

from casper.models import (
    DEPTH_CAPS,
    AdaptedPlan,
    Fact,
    FactKind,
    FactModel,
    Glossary,
    JargonLevel,
    Persona,
    Plan,
    PlanSection,
    Structure,
)

_KEYWORD_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SOURCE_KEYWORD_BOOST = 0.3
_MIN_KEYWORD_LEN = 4


def plan_structure(model: FactModel, structure: Structure) -> Plan:
    """Assign each fact at most once to the first matching section in structure order."""
    used_ids: set[str] = set()
    plan_sections: list[PlanSection] = []
    warnings: list[str] = []

    for section in structure.sections:
        accepted = frozenset(section.fact_kinds)
        matched = [
            fact
            for fact in model.facts
            if fact.id not in used_ids and fact.kind in accepted
        ]
        matched.sort(key=lambda f: (-f.salience, f.order))
        for fact in matched:
            used_ids.add(fact.id)
        plan_sections.append(PlanSection(section=section, facts=tuple(matched)))
        if section.required and not matched:
            warnings.append(f"Required section '{section.name}' has no matching facts.")

    unused_facts = tuple(
        sorted((f for f in model.facts if f.id not in used_ids), key=lambda f: f.order)
    )
    if unused_facts:
        warnings.append(
            f"{len(unused_facts)} fact(s) did not fit any section in '{structure.id}'."
        )

    return Plan(
        structure=structure,
        sections=tuple(plan_sections),
        unused_facts=unused_facts,
        warnings=tuple(warnings),
    )


def _source_keywords(source: Persona) -> frozenset[str]:
    """Extract lowercase keywords (len >= 4) from source persona priorities, vocab, and concerns."""
    keywords: set[str] = set()
    for phrase in (*source.priorities, *source.vocabulary_include, *source.typical_concerns):
        cleaned = phrase.strip().lower()
        if len(cleaned) >= _MIN_KEYWORD_LEN and " " not in cleaned:
            keywords.add(cleaned)
        for token in _KEYWORD_TOKEN_RE.findall(cleaned):
            if len(token) >= _MIN_KEYWORD_LEN:
                keywords.add(token)
    return frozenset(keywords)


def _fact_priority_score(fact: Fact, source_keywords: frozenset[str]) -> float:
    """Compute salience plus +0.3 boost when fact text mentions a source keyword."""
    if not source_keywords:
        return fact.salience
    lower = fact.text.lower()
    if any(kw in lower for kw in source_keywords):
        return fact.salience + _SOURCE_KEYWORD_BOOST
    return fact.salience


def _choose_cta_style(source: Persona, target: Persona) -> str | None:
    """Pick first shared CTA style, else target's first, else source's first."""
    source_styles = set(source.cta_styles)
    for style in target.cta_styles:
        if style in source_styles:
            return style
    if target.cta_styles:
        return target.cta_styles[0]
    if source.cta_styles:
        return source.cta_styles[0]
    return None


def adapt(plan: Plan, source: Persona, target: Persona, glossary: Glossary) -> AdaptedPlan:
    """Adapt a structural plan to source and target personas and active glossary."""
    cap = DEPTH_CAPS[target.detail_depth]
    source_keywords = _source_keywords(source)
    warnings: list[str] = list(plan.warnings)

    capped_sections: list[PlanSection] = []
    for plan_section in plan.sections:
        ranked = sorted(
            plan_section.facts,
            key=lambda f: (-_fact_priority_score(f, source_keywords), f.order),
        )
        kept = sorted(ranked[:cap], key=lambda f: f.order)
        dropped = len(ranked) - len(kept)
        if dropped > 0:
            warnings.append(
                f"Section '{plan_section.section.name}' capped at {cap} fact(s) "
                f"for depth '{target.detail_depth.value}' ({dropped} omitted)."
            )
        capped_sections.append(PlanSection(section=plan_section.section, facts=tuple(kept)))

    priority_index = {name: idx for idx, name in enumerate(target.section_priority)}
    indexed = list(enumerate(capped_sections))
    indexed.sort(
        key=lambda item: (
            0 if item[1].section.name in priority_index else 1,
            priority_index.get(item[1].section.name, item[0]),
        )
    )
    ordered_sections = tuple(ps for _, ps in indexed)

    if target.jargon_level == JargonLevel.LOW:
        substitutions: dict[str, str] = dict(glossary.plain)
        substitutions.update(glossary.preferred)
    else:
        substitutions = dict(glossary.preferred)

    has_kept_ask = any(
        fact.kind == FactKind.ASK for ps in ordered_sections for fact in ps.facts
    )
    cta_style = _choose_cta_style(source, target) if has_kept_ask else None

    return AdaptedPlan(
        structure=plan.structure,
        source=source,
        target=target,
        sections=ordered_sections,
        substitutions=substitutions,
        cta_style=cta_style,
        warnings=tuple(warnings),
    )
