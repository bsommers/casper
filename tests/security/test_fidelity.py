"""TC-029: Adversarial fidelity security tests in STRICT and ASSISTED modes."""

from __future__ import annotations

from typing import Any

import networkx as nx
import pytest

from casper.libraries import load_libraries
from casper.models import (
    AdaptedPlan,
    BackendKind,
    CheckLevel,
    Constraints,
    DepthLevel,
    Draft,
    DraftSection,
    Fact,
    FactKind,
    FactModel,
    FidelityMode,
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
from casper.validator import ANTONYM_PAIRS, validate


@pytest.fixture(scope="module")
def nlp() -> Any:
    return load_nlp(ner=False)


@pytest.fixture(scope="module")
def libs() -> Any:
    return load_libraries()


def _fact(fid: str, text: str, *, kind: FactKind = FactKind.STATUS) -> Fact:
    return Fact(id=fid, kind=kind, text=text, source="<inline>", order=0)


def _bundle(
    facts: tuple[Fact, ...],
    sentences: tuple[Sentence, ...],
    *,
    title: str | None = None,
    declared_additions: frozenset[str] = frozenset(),
    backend: BackendKind = BackendKind.RULES,
) -> tuple[Draft, AdaptedPlan, FactModel, Modality]:
    sec = Section(
        name="status",
        purpose="State",
        fact_kinds=(FactKind.STATUS, FactKind.PROGRESS, FactKind.RISK),
        required=True,
        min_words=1,
        max_words=200,
        heading="Status",
    )
    structure = Structure(
        id="status_update",
        goal="Status",
        sections=(sec,),
        compatible_modalities=("memo",),
        default_target_personas=("management",),
    )
    source = Persona(
        id="developer",
        kind=PersonaKind.SOURCE,
        priorities=("reliability",),
        vocabulary_include=(),
        vocabulary_avoid=(),
        detail_depth=DepthLevel.HIGH,
        jargon_level=JargonLevel.HIGH,
        framing_patterns=(),
        typical_concerns=(),
        cta_styles=("direct",),
        section_priority=("status",),
    )
    target = Persona(
        id="management",
        kind=PersonaKind.TARGET,
        priorities=("schedule",),
        vocabulary_include=(),
        vocabulary_avoid=(),
        detail_depth=DepthLevel.HIGH,
        jargon_level=JargonLevel.HIGH,
        framing_patterns=(),
        typical_concerns=(),
        cta_styles=("direct",),
        section_priority=("status",),
    )
    plan = AdaptedPlan(
        structure=structure,
        source=source,
        target=target,
        sections=(PlanSection(section=sec, facts=facts),),
        substitutions={},
        cta_style=None,
    )
    fm = FactModel(
        facts=facts,
        graph=nx.DiGraph(),
        input_hashes={"<inline>": "0" * 64},
        digest="b" * 64,
    )
    draft = Draft(
        title=title,
        sections=(DraftSection(name="status", heading="Status", sentences=sentences),),
        backend=backend,
        declared_additions=declared_additions,
    )
    modality = Modality(
        id="memo",
        markup=MarkupKind.MARKDOWN,
        max_words=800,
        max_chars=6000,
        title=True,
        headings="h2",
        bullets=True,
        description="Memo",
    )
    return draft, plan, fm, modality


def _error_codes(res: Any) -> set[str]:
    return {f.code for f in res.findings if f.level == CheckLevel.ERROR}


# ---------------------------------------------------------------------------
# Number & sign attacks (STRICT & ASSISTED)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [FidelityMode.STRICT, FidelityMode.ASSISTED])
def test_attack_invented_number_rejected(mode: FidelityMode, libs: Any, nlp: Any) -> None:
    f1 = _fact("f001", "The cloud budget remained $100 this quarter.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text="The cloud budget reached $999 this quarter.", fact_ids=("f001",)),),
    )
    res = validate(
        draft, plan, fm, None, Constraints(), mod, fidelity_mode=mode, glossary=libs.glossary, nlp=nlp
    )
    assert not res.ok
    assert "unsupported-number" in _error_codes(res)


@pytest.mark.parametrize("mode", [FidelityMode.STRICT, FidelityMode.ASSISTED])
@pytest.mark.parametrize(
    ("fact_text", "attack_text"),
    [
        ("Conversion changed by +12%.", "Conversion changed by -12%."),
        ("Conversion changed by +12%.", "Conversion changed by 12%."),
        ("Conversion changed by 12%.", "Conversion changed by -12%."),
        ("Error count was 12.", "Error rate was 12%."),
    ],
)
def test_attack_flipped_sign_or_percent_rejected(
    mode: FidelityMode, fact_text: str, attack_text: str, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", fact_text)
    draft, plan, fm, mod = _bundle((f1,), (Sentence(text=attack_text, fact_ids=("f001",)),))
    res = validate(
        draft, plan, fm, None, Constraints(), mod, fidelity_mode=mode, glossary=libs.glossary, nlp=nlp
    )
    assert not res.ok
    assert "unsupported-number" in _error_codes(res)


# ---------------------------------------------------------------------------
# Invented proper-name attacks (mid-sentence AND sentence-initial, ASSISTED)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attack_sentence",
    [
        "The vendor ZorgCorp launched the update.",
        "The release was signed off by Bob.",
        "The release now targets iOS devices.",
        "ZorgCorp launched the update.",
        "Alice launched the update.",
        "NASA launched the update.",
        "iOS launched the update.",
        '"Alice" launched the update.',
    ],
)
def test_attack_invented_name_mid_and_initial_rejected_in_assisted(
    attack_sentence: str, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", "The team launched the update.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text=attack_sentence, fact_ids=("f001",)),),
        backend=BackendKind.CLAUDE,
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res.ok
    assert "unsupported-name" in _error_codes(res)


# ---------------------------------------------------------------------------
# Polarity flip attacks & benign idiom non-regression (ASSISTED)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fact_text", "attack_text"),
    [
        ("The migration is approved.", "The migration is not approved."),
        ("The team did not ship the patch.", "The team shipped the patch."),
        ("The team can deploy today.", "The team cannot deploy today."),
        ("The pipeline succeeded.", "The pipeline failed."),
        ("Engineers can reach the cluster.", "Engineers are unable to reach the cluster."),
    ],
)
def test_attack_single_fact_polarity_flip_rejected(
    fact_text: str, attack_text: str, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", fact_text)
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text=attack_text, fact_ids=("f001",)),),
        backend=BackendKind.AGY,
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res.ok
    assert "polarity-mismatch" in _error_codes(res)


def test_attack_multi_fact_polarity_flip_and_mixed_allowance(libs: Any, nlp: Any) -> None:
    f_pos1 = _fact("f001", "Service alpha is healthy.")
    f_pos2 = _fact("f002", "Service beta is healthy.")
    f_neg1 = _fact("f003", "Service alpha is not ready.")
    f_neg2 = _fact("f004", "Service beta is not ready.")

    # All affirmative cited facts vs negated sentence -> ERROR
    draft_pos_to_neg, plan, fm, mod = _bundle(
        (f_pos1, f_pos2),
        (Sentence(text="Neither service is healthy.", fact_ids=("f001", "f002")),),
        backend=BackendKind.CLAUDE,
    )
    res_1 = validate(
        draft_pos_to_neg,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res_1.ok
    assert "polarity-mismatch" in _error_codes(res_1)

    # All negated cited facts vs affirmative sentence -> ERROR
    draft_neg_to_pos, plan2, fm2, mod2 = _bundle(
        (f_neg1, f_neg2),
        (Sentence(text="Both services are ready.", fact_ids=("f003", "f004")),),
        backend=BackendKind.CLAUDE,
    )
    res_2 = validate(
        draft_neg_to_pos,
        plan2,
        fm2,
        None,
        Constraints(),
        mod2,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res_2.ok
    assert "polarity-mismatch" in _error_codes(res_2)

    # Mixed polarity facts -> allowed (not all agree)
    draft_mixed, plan3, fm3, mod3 = _bundle(
        (f_pos1, f_neg2),
        (Sentence(text="Service alpha is healthy while beta is not ready.", fact_ids=("f001", "f004")),),
        backend=BackendKind.CLAUDE,
    )
    res_3 = validate(
        draft_mixed,
        plan3,
        fm3,
        None,
        Constraints(),
        mod3,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert res_3.ok
    assert "polarity-mismatch" not in _error_codes(res_3)


@pytest.mark.parametrize(
    ("src_term", "opp_term"),
    [(a, b) for a, b in ANTONYM_PAIRS] + [(b, a) for a, b in ANTONYM_PAIRS],
)
def test_attack_antonym_flip_all_pairs_both_directions(
    src_term: str, opp_term: str, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", f"The rollout was {src_term} today.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text=f"The rollout was {opp_term} today.", fact_ids=("f001",)),),
        backend=BackendKind.CLAUDE,
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res.ok
    assert "polarity-mismatch" in _error_codes(res)


@pytest.mark.parametrize(
    ("fact_text", "benign_sentence"),
    [
        ("Latency improved across regions.", "Not only did latency improve across regions."),
        ("Deliver the build by Friday.", "Deliver the build no later than Friday."),
        ("Deployment completed cleanly.", "Deployment completed with no issues."),
        ("Deployment completed cleanly.", "Deployment completed with zero issues."),
        ("The team didn't change the schedule.", "The team did not change the schedule."),
    ],
)
def test_benign_idioms_do_not_false_positive(
    fact_text: str, benign_sentence: str, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", fact_text)
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text=benign_sentence, fact_ids=("f001",)),),
        backend=BackendKind.CLAUDE,
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert res.ok
    assert "polarity-mismatch" not in _error_codes(res)


# ---------------------------------------------------------------------------
# Traceability, undeclared additions, banned terms, and glossary checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [FidelityMode.STRICT, FidelityMode.ASSISTED])
def test_attack_uncited_frame_with_facts_and_unknown_fact(
    mode: FidelityMode, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", "Rollout is healthy.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (
            Sentence(text="Invented uncited sentence.", fact_ids=(), frame=False),
            Sentence(text="Please approve.", fact_ids=("f001",), frame=True),
            Sentence(text="Rollout is healthy.", fact_ids=("f999",), frame=False),
        ),
    )
    res = validate(
        draft, plan, fm, None, Constraints(), mod, fidelity_mode=mode, glossary=libs.glossary, nlp=nlp
    )
    assert not res.ok
    assert {"untraced", "frame-with-facts", "unknown-fact"} <= _error_codes(res)


def test_attack_strict_undeclared_rule_and_smart_quote_contraction(libs: Any, nlp: Any) -> None:
    f1 = _fact("f001", "The service does not restart automatically.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text="The service doesn\u2019t restart automatically.", fact_ids=("f001",)),),
        declared_additions=frozenset(),
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res.ok
    assert "undeclared-addition" in _error_codes(res)


def test_attack_strict_negation_word_not_bypassed_by_short_len(libs: Any, nlp: Any) -> None:
    f1 = _fact("f001", "The service restarts automatically.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text="No service restarts automatically.", fact_ids=("f001",)),),
    )
    res = validate(
        draft,
        plan,
        fm,
        None,
        Constraints(),
        mod,
        fidelity_mode=FidelityMode.STRICT,
        glossary=libs.glossary,
        nlp=nlp,
    )
    assert not res.ok
    assert "unsupported-claim" in _error_codes(res)


@pytest.mark.parametrize("mode", [FidelityMode.STRICT, FidelityMode.ASSISTED])
def test_attack_banned_word_in_body_and_title_and_leftover_preferred(
    mode: FidelityMode, libs: Any, nlp: Any
) -> None:
    f1 = _fact("f001", "We utilize disruptive patterns.")
    draft, plan, fm, mod = _bundle(
        (f1,),
        (Sentence(text="We utilize disruptive patterns.", fact_ids=("f001",)),),
        title="Synergy review",
    )
    res = validate(
        draft, plan, fm, None, Constraints(), mod, fidelity_mode=mode, glossary=libs.glossary, nlp=nlp
    )
    assert not res.ok
    banned_findings = [f for f in res.findings if f.code == "banned-term"]
    assert len(banned_findings) == 2
    assert all(f.level == CheckLevel.ERROR for f in banned_findings)
    assert any(f.code == "glossary" and f.level == CheckLevel.WARNING for f in res.findings)
