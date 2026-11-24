"""Unit tests for src/casper/validator.py (TC-023 + all 22 check codes)."""

from __future__ import annotations

from typing import Any

import networkx as nx
import pytest

from casper.libraries import load_libraries
from casper.modalities import count_rendered
from casper.models import (
    AdaptedPlan,
    BackendKind,
    CheckLevel,
    ConfidenceBand,
    Constraints,
    DepthLevel,
    Document,
    Draft,
    DraftSection,
    Fact,
    FactKind,
    FactModel,
    FidelityMode,
    Glossary,
    JargonLevel,
    MarkupKind,
    Modality,
    Persona,
    PersonaKind,
    PlanSection,
    Section,
    Sentence,
    Structure,
)
from casper.parsing import load_nlp
from casper.profile import build_profile
from casper.validator import validate


@pytest.fixture(scope="module")
def nlp() -> Any:
    return load_nlp(ner=False)


@pytest.fixture(scope="module")
def libs() -> Any:
    return load_libraries()


@pytest.fixture(scope="module")
def sample_voice_profile(tmp_path_factory: pytest.TempPathFactory, nlp: Any) -> dict[str, Any]:
    """Build a real author profile from synthetic prose for voice scoring tests."""
    tmp = tmp_path_factory.mktemp("validator_voice")
    base_sentences = [
        "The release team tracks reliability metrics before expanding rollout scope.",
        "We measure response time across every critical service each morning.",
        "When latency rises above baseline, engineers pause changes and isolate the cause.",
        "Clear ownership keeps delivery predictable even when priorities shift unexpectedly.",
        "Short updates work best when every claim links directly to verified evidence.",
        "Teams avoid unnecessary jargon so stakeholders can make fast decisions.",
        "Before approving a migration, leaders review risks and concrete fallback plans.",
        "Measured increments reduce operational surprises during busy launch weeks.",
    ]
    paths = []
    for idx in range(2):
        p = tmp / f"sample_{idx}.md"
        body = (
            f"# Engineering Notes {idx}\n\n"
            f"## Overview\n\n"
            + " ".join(base_sentences * 3)
            + "\n\n## Execution\n\n"
            + " ".join(base_sentences * 3)
            + "\n"
        )
        p.write_text(body, encoding="utf-8")
        paths.append(p)
    return build_profile("alex", "Alex", paths, min_words=150, nlp=nlp)


def _make_fact(
    fid: str,
    text: str,
    *,
    kind: FactKind = FactKind.STATUS,
    order: int = 0,
    entities: tuple[str, ...] = (),
    owners: tuple[str, ...] = (),
) -> Fact:
    return Fact(
        id=fid,
        kind=kind,
        text=text,
        source="<inline>",
        order=order,
        entities=entities,
        owners=owners,
    )


def _make_fact_model(*facts: Fact) -> FactModel:
    return FactModel(
        facts=tuple(facts),
        graph=nx.DiGraph(),
        input_hashes={"<inline>": "0" * 64},
        digest="a" * 64,
    )


def _make_target_persona(
    *,
    detail_depth: DepthLevel = DepthLevel.MEDIUM,
    jargon_level: JargonLevel = JargonLevel.LOW,
    vocabulary_avoid: tuple[str, ...] = ("mutex", "refactor"),
    section_priority: tuple[str, ...] = ("status", "risks", "next_steps"),
) -> Persona:
    return Persona(
        id="management",
        kind=PersonaKind.TARGET,
        priorities=("schedule", "risk"),
        vocabulary_include=("timeline", "impact"),
        vocabulary_avoid=vocabulary_avoid,
        detail_depth=detail_depth,
        jargon_level=jargon_level,
        framing_patterns=("bottom_line_up_front",),
        typical_concerns=("delay",),
        cta_styles=("approval",),
        section_priority=section_priority,
    )


def _make_source_persona() -> Persona:
    return Persona(
        id="developer",
        kind=PersonaKind.SOURCE,
        priorities=("reliability",),
        vocabulary_include=("build",),
        vocabulary_avoid=(),
        detail_depth=DepthLevel.HIGH,
        jargon_level=JargonLevel.HIGH,
        framing_patterns=("evidence_first",),
        typical_concerns=("blocker",),
        cta_styles=("direct",),
        section_priority=("status",),
    )


def _make_structure() -> Structure:
    return Structure(
        id="status_update",
        goal="Communicate status",
        sections=(
            Section(
                name="status",
                purpose="Current state",
                fact_kinds=(FactKind.STATUS,),
                required=True,
                min_words=5,
                max_words=80,
                heading="Status",
            ),
            Section(
                name="risks",
                purpose="Active risks",
                fact_kinds=(FactKind.RISK,),
                required=False,
                min_words=0,
                max_words=80,
                heading="Risks",
            ),
            Section(
                name="next_steps",
                purpose="Planned actions",
                fact_kinds=(FactKind.NEXT_STEP,),
                required=False,
                min_words=0,
                max_words=80,
                heading="Next Steps",
            ),
        ),
        compatible_modalities=("plain", "memo", "article"),
        default_target_personas=("management",),
    )


def _make_plan(
    facts: tuple[Fact, ...],
    *,
    target: Persona | None = None,
    substitutions: dict[str, str] | None = None,
    warnings: tuple[str, ...] = (),
) -> AdaptedPlan:
    structure = _make_structure()
    return AdaptedPlan(
        structure=structure,
        source=_make_source_persona(),
        target=target or _make_target_persona(),
        sections=(PlanSection(section=structure.sections[0], facts=facts),),
        substitutions=substitutions if substitutions is not None else {"utilize": "use"},
        cta_style=None,
        warnings=warnings,
    )


def _plain_modality(*, max_words: int | None = 200, max_chars: int | None = 1400) -> Modality:
    return Modality(
        id="plain",
        markup=MarkupKind.PLAIN,
        max_words=max_words,
        max_chars=max_chars,
        title=False,
        headings="none",
        bullets=False,
        description="Plain text",
    )


def _html_modality(*, max_words: int | None = 200, max_chars: int | None = 2000) -> Modality:
    return Modality(
        id="article",
        markup=MarkupKind.HTML,
        max_words=max_words,
        max_chars=max_chars,
        title=True,
        headings="h2",
        bullets=False,
        description="HTML article",
    )


def _codes(validation: Any) -> list[str]:
    return [f.code for f in validation.findings]


# ---------------------------------------------------------------------------
# TC-023: Exact length boundaries (max_words -1 / exact / +1; max_chars -1 / exact / +1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "modality",
    [
        _plain_modality(max_words=None, max_chars=None),
        _html_modality(max_words=None, max_chars=None),
    ],
    ids=["plain", "html"],
)
def test_tc023_word_and_char_exact_boundaries(modality: Modality, libs: Any) -> None:
    fact = _make_fact("f001", "The billing rollout finished on schedule.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))
    draft = Draft(
        title="Rollout Update" if modality.title else None,
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text="The billing rollout finished on schedule.", fact_ids=("f001",)),),
            ),
        ),
    )

    words, chars = count_rendered(draft, modality)

    # max_words: exact and +1 above rendered count pass; -1 fails too-long.
    res_word_ok_above = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(max_words=words + 1),
        modality,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_word_ok_above.ok
    assert "too-long" not in _codes(res_word_ok_above)

    res_word_exact = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(max_words=words),
        modality,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_word_exact.ok
    assert "too-long" not in _codes(res_word_exact)

    res_word_over = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(max_words=words - 1),
        modality,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res_word_over.ok
    assert "too-long" in _codes(res_word_over)
    assert any(f.code == "too-long" and f.level == CheckLevel.ERROR for f in res_word_over.findings)

    # max_chars: exact and +1 above rendered count pass; -1 fails too-long-chars.
    res_char_ok_above = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(max_chars=chars + 1),
        modality,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_char_ok_above.ok
    assert "too-long-chars" not in _codes(res_char_ok_above)

    res_char_exact = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(max_chars=chars),
        modality,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_char_exact.ok
    assert "too-long-chars" not in _codes(res_char_exact)

    res_char_over = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(max_chars=chars - 1),
        modality,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res_char_over.ok
    assert any(
        f.code == "too-long-chars" and f.level == CheckLevel.ERROR for f in res_char_over.findings
    )


def test_modality_fallback_limits_when_constraints_none(libs: Any) -> None:
    fact = _make_fact("f001", "The billing rollout finished on schedule.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))
    draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text=fact.text, fact_ids=("f001",)),),
            ),
        )
    )
    tight_mod = _plain_modality(max_words=3, max_chars=10)
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        tight_mod,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res.ok
    assert {"too-long", "too-long-chars"} <= set(_codes(res))


# ---------------------------------------------------------------------------
# Traceability, empty draft, numeric & strict/assisted checks
# ---------------------------------------------------------------------------


def test_empty_draft_flags_empty_and_skips_voice(
    libs: Any, sample_voice_profile: dict[str, Any], nlp: Any
) -> None:
    fact = _make_fact("f001", "Status is green.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))
    empty_draft = Draft(
        sections=(
            DraftSection(name="status", heading="Status", sentences=(Sentence(text="   "),)),
        )
    )
    res = validate(
        empty_draft,
        plan,
        fm,
        sample_voice_profile,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res.ok
    assert "empty" in _codes(res)
    assert "voice-unscorable" not in _codes(res)
    assert res.voice_report is None


def test_frame_with_facts_untraced_and_unknown_fact(libs: Any) -> None:
    fact = _make_fact("f001", "The rollout is healthy.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))
    draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(text="Please confirm.", fact_ids=("f001",), frame=True),
                    Sentence(text="No citations here.", fact_ids=(), frame=False),
                    Sentence(text="Unknown reference.", fact_ids=("f999",), frame=False),
                ),
            ),
        )
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res.ok
    codes = set(_codes(res))
    assert {"frame-with-facts", "untraced", "unknown-fact"} <= codes


def test_numeric_comma_normalization_and_sign_enforcement(libs: Any) -> None:
    fact = _make_fact("f001", "Throughput reached 1,200 requests with +12% growth.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))

    good_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(
                        text="Throughput reached 1200 requests with +12% growth.",
                        fact_ids=("f001",),
                    ),
                ),
            ),
        )
    )
    res_ok = validate(
        good_draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_ok.ok

    flipped_sign_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(
                        text="Throughput reached 1200 requests with -12% growth.",
                        fact_ids=("f001",),
                    ),
                ),
            ),
        )
    )
    res_bad = validate(
        flipped_sign_draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res_bad.ok
    assert "unsupported-number" in _codes(res_bad)


def test_strict_declared_additions_and_unsupported_claim(libs: Any) -> None:
    fact = _make_fact("f001", "We do not ship unstable builds.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,), substitutions={"utilize": "use"})

    # Valid declared contraction + transition rule token passes.
    valid_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(
                        text="Additionally, we don't ship unstable builds.",
                        fact_ids=("f001",),
                    ),
                ),
            ),
        ),
        declared_additions=frozenset({"additionally", "don't"}),
    )
    res_ok = validate(
        valid_draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_ok.ok

    # Undeclared rule token in sentence -> undeclared-addition.
    undeclared_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(
                        text="Additionally, we don't ship unstable builds.",
                        fact_ids=("f001",),
                    ),
                ),
            ),
        ),
        declared_additions=frozenset(),
    )
    res_undecl = validate(
        undeclared_draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res_undecl.ok
    assert "undeclared-addition" in _codes(res_undecl)

    # Unregistered token stuffed into Draft.declared_additions -> undeclared-addition + unsupported-claim.
    rogue_declared = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(
                        text="We do not ship mythical builds.",
                        fact_ids=("f001",),
                    ),
                ),
            ),
        ),
        declared_additions=frozenset({"mythical"}),
    )
    res_rogue = validate(
        rogue_declared,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res_rogue.ok
    assert {"undeclared-addition", "unsupported-claim"} <= set(_codes(res_rogue))


def test_assisted_reworded_warning_and_allowed_names(libs: Any, nlp: Any) -> None:
    fact = _make_fact(
        "f001",
        "The migration is progressing smoothly.",
        entities=("Atlas",),
        owners=("Dana",),
    )
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))
    draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(
                        text="Overall, Dana reports Atlas migration remains steady.",
                        fact_ids=("f001",),
                    ),
                ),
            ),
        ),
        backend=BackendKind.CLAUDE,
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert res.ok
    assert res.fidelity_mode == FidelityMode.ASSISTED
    assert any(f.code == "reworded" and f.level == CheckLevel.WARNING for f in res.findings)
    assert "unsupported-name" not in _codes(res)


# ---------------------------------------------------------------------------
# Banned terms, glossary, persona checks & persona_score
# ---------------------------------------------------------------------------


def test_banned_term_and_glossary_in_title_and_body(libs: Any) -> None:
    fact = _make_fact("f001", "We utilize synergy across teams.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,))
    draft = Draft(
        title="Prior to launch: rockstar customban",
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text=fact.text, fact_ids=("f001",)),),
            ),
        ),
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(banned=("customban",)),
        _html_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert not res.ok
    banned = [f for f in res.findings if f.code == "banned-term"]
    gloss = [f for f in res.findings if f.code == "glossary"]
    assert len(banned) >= 3  # rockstar, customban in title; synergy in body
    assert all(f.level == CheckLevel.ERROR for f in banned)
    assert len(gloss) >= 2  # prior to in title; utilize in body
    assert all(f.level == CheckLevel.WARNING for f in gloss)


def test_persona_checks_and_score_progression(libs: Any) -> None:
    f1 = _make_fact("f001", "The mutex refactor improved latency significantly.")
    f2 = _make_fact("f002", "The second check completed.")
    f3 = _make_fact("f003", "Risk remains manageable.", kind=FactKind.RISK)
    fm = _make_fact_model(f1, f2, f3)
    target = _make_target_persona(
        detail_depth=DepthLevel.LOW,  # cap = 1
        jargon_level=JargonLevel.LOW,
        vocabulary_avoid=("mutex",),
        section_priority=("status", "risks"),
    )
    plan = _make_plan((f1, f2, f3), target=target)

    # All 4 persona categories fail -> persona_score == 0.0
    bad_all = Draft(
        sections=(
            DraftSection(
                name="risks",
                heading="Risks",
                sentences=(Sentence(text=f3.text, fact_ids=("f003",)),),
            ),
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(text=f1.text, fact_ids=("f001",)),
                    Sentence(text=f2.text, fact_ids=("f002",)),
                ),
            ),
        )
    )
    res_0 = validate(
        bad_all,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_0.ok  # persona checks are WARNINGs
    assert res_0.persona_score == 0.0
    assert {"persona-avoid", "persona-jargon", "persona-depth", "persona-order"} <= set(
        _codes(res_0)
    )

    # Fix order only -> 25.0
    ordered = Draft(sections=(bad_all.sections[1], bad_all.sections[0]))
    res_25 = validate(
        ordered,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_25.persona_score == 25.0

    # Fix depth too (frame sentence does not count toward depth cap) -> 50.0
    capped = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(text=f1.text, fact_ids=("f001",)),
                    Sentence(text="Please confirm.", fact_ids=(), frame=True),
                ),
            ),
            bad_all.sections[0],
        )
    )
    res_50 = validate(
        capped,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_50.persona_score == 50.0
    assert "persona-depth" not in _codes(res_50)

    # High jargon target does NOT emit persona-jargon -> 75.0
    high_jargon_plan = _make_plan(
        (f1, f3),
        target=_make_target_persona(
            detail_depth=DepthLevel.LOW,
            jargon_level=JargonLevel.HIGH,
            vocabulary_avoid=("mutex",),
            section_priority=("status", "risks"),
        ),
    )
    res_75 = validate(
        capped,
        high_jargon_plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_75.persona_score == 75.0
    assert "persona-jargon" not in _codes(res_75)

    # Clean draft -> 100.0
    clean_fact = _make_fact("f001", "The rollout finished cleanly.")
    clean_fm = _make_fact_model(clean_fact)
    clean_plan = _make_plan((clean_fact,), target=target)
    clean_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text=clean_fact.text, fact_ids=("f001",)),),
            ),
        )
    )
    res_100 = validate(
        clean_draft,
        clean_plan,
        clean_fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res_100.ok
    assert res_100.persona_score == 100.0


# ---------------------------------------------------------------------------
# Plan completeness & voice conformance checks
# ---------------------------------------------------------------------------


def test_plan_missing_required_section_and_warning_propagation(libs: Any) -> None:
    risk_fact = _make_fact("f001", "A vendor delay is possible.", kind=FactKind.RISK)
    fm = _make_fact_model(risk_fact)
    plan = _make_plan(
        (risk_fact,),
        warnings=(
            "Required section 'status' has no matching facts.",
            "Required section 'summary' had no source data.",
        ),
    )
    draft = Draft(
        sections=(
            DraftSection(
                name="risks",
                heading="Risks",
                sentences=(Sentence(text=risk_fact.text, fact_ids=("f001",)),),
            ),
        )
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
    )
    assert res.ok
    plan_findings = [f for f in res.findings if f.code == "plan"]
    assert len(plan_findings) == 2
    assert all(f.level == CheckLevel.WARNING for f in plan_findings)


def test_voice_unscorable_low_confidence_and_threshold(
    libs: Any, sample_voice_profile: dict[str, Any], nlp: Any
) -> None:
    # 1. Punctuation-only non-empty draft -> voice-unscorable (WARNING)
    punct_fact = _make_fact("f001", "...")
    punct_fm = _make_fact_model(punct_fact)
    punct_plan = _make_plan((punct_fact,))
    punct_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text="...", fact_ids=("f001",)),),
            ),
        )
    )
    res_unscorable = validate(
        punct_draft,
        punct_plan,
        punct_fm,
        sample_voice_profile,
        Constraints(min_voice=50.0),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert res_unscorable.ok
    assert res_unscorable.voice_report is None
    assert any(
        f.code == "voice-unscorable" and f.level == CheckLevel.WARNING
        for f in res_unscorable.findings
    )

    # 2. Short scorable draft (<250 words) -> voice-low-confidence (WARNING) + voice-below-threshold (ERROR)
    short_fact = _make_fact("f001", "The release team tracks reliability metrics daily.")
    short_fm = _make_fact_model(short_fact)
    short_plan = _make_plan((short_fact,))
    short_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(
                    Sentence(text=short_fact.text, fact_ids=("f001",)),
                    Sentence(text="Please confirm.", fact_ids=(), frame=True),
                ),
            ),
        )
    )
    res_below = validate(
        short_draft,
        short_plan,
        short_fm,
        sample_voice_profile,
        Constraints(min_voice=100.1),
        _html_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res_below.ok
    assert res_below.voice_report is not None
    assert res_below.voice_report.confidence == ConfidenceBand.LOW
    assert any(
        f.code == "voice-low-confidence" and f.level == CheckLevel.WARNING
        for f in res_below.findings
    )
    assert any(
        f.code == "voice-below-threshold" and f.level == CheckLevel.ERROR
        for f in res_below.findings
    )

    # 3. Same draft with achievable threshold passes.
    res_pass = validate(
        short_draft,
        short_plan,
        short_fm,
        sample_voice_profile,
        Constraints(min_voice=0.0),
        _html_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert res_pass.ok
    assert "voice-below-threshold" not in _codes(res_pass)
    assert isinstance(res_pass.to_dict(), dict)

    # 4. Longer draft (>=250 words) avoids voice-low-confidence.
    long_text = " ".join(
        ["The release team tracks reliability metrics before expanding rollout scope."] * 30
    )
    long_fact = _make_fact("f001", long_text)
    long_fm = _make_fact_model(long_fact)
    long_plan = _make_plan((long_fact,))
    long_draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text=long_text, fact_ids=("f001",)),),
            ),
        )
    )
    res_med = validate(
        long_draft,
        long_plan,
        long_fm,
        sample_voice_profile,
        Constraints(max_words=1000, max_chars=10000),
        _plain_modality(max_words=1000, max_chars=10000),
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert res_med.voice_report is not None
    assert res_med.voice_report.confidence in {ConfidenceBand.MEDIUM, ConfidenceBand.HIGH}
    assert "voice-low-confidence" not in _codes(res_med)


def test_glossary_empty_terms_and_doc_serialization() -> None:
    empty_glossary = Glossary(plain={"": ""}, preferred={"": ""}, banned=("",))
    fact = _make_fact("f001", "Work is steady.")
    fm = _make_fact_model(fact)
    plan = _make_plan((fact,), target=_make_target_persona(vocabulary_avoid=("",)))
    draft = Draft(
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text=fact.text, fact_ids=("f001",)),),
            ),
        )
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(banned=("",)),
        _plain_modality(),
        fidelity_mode=FidelityMode.STRICT,
        glossary=empty_glossary,
    )
    assert res.ok
    assert isinstance(Document(source="x", format="plain").to_dict(), dict)
