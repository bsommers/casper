"""Unit tests for structure planning and persona adaptation (TC-012)."""

from __future__ import annotations

import networkx as nx
import pytest

from casper.libraries import load_libraries
from casper.models import (
    DepthLevel,
    Fact,
    FactKind,
    FactModel,
    Glossary,
    JargonLevel,
    Persona,
    PersonaKind,
    Section,
    Structure,
)
from casper.planner import adapt, plan_structure


def _fact(
    fid: str,
    kind: FactKind,
    text: str,
    order: int,
    salience: float = 1.0,
) -> Fact:
    return Fact(
        id=fid,
        kind=kind,
        text=text,
        source="<inline>",
        order=order,
        salience=salience,
    )


def _model(facts: list[Fact]) -> FactModel:
    return FactModel(
        facts=tuple(facts),
        graph=nx.DiGraph(),
        input_hashes={"<inline>": "0" * 64},
        digest="0" * 64,
    )


def _persona(
    *,
    pid: str = "p",
    kind: PersonaKind = PersonaKind.TARGET,
    priorities: tuple[str, ...] = (),
    vocabulary_include: tuple[str, ...] = (),
    typical_concerns: tuple[str, ...] = (),
    detail_depth: DepthLevel = DepthLevel.MEDIUM,
    jargon_level: JargonLevel = JargonLevel.MEDIUM,
    cta_styles: tuple[str, ...] = ("direct",),
    section_priority: tuple[str, ...] = (),
) -> Persona:
    return Persona(
        id=pid,
        kind=kind,
        priorities=priorities,
        vocabulary_include=vocabulary_include,
        vocabulary_avoid=(),
        detail_depth=detail_depth,
        jargon_level=jargon_level,
        framing_patterns=(),
        typical_concerns=typical_concerns,
        cta_styles=cta_styles,
        section_priority=section_priority,
    )


def test_plan_structure_single_use_ordering_unused_and_required_warning() -> None:
    structure = Structure(
        id="custom",
        goal="Test single-use assignment",
        sections=(
            Section(
                name="primary",
                purpose="First status bucket",
                fact_kinds=(FactKind.STATUS, FactKind.METRIC),
                required=True,
                min_words=0,
                max_words=100,
                heading="Primary",
            ),
            Section(
                name="overlap",
                purpose="Second bucket sharing STATUS kind",
                fact_kinds=(FactKind.STATUS,),
                required=True,
                min_words=0,
                max_words=100,
                heading="Overlap",
            ),
            Section(
                name="risks",
                purpose="Risks",
                fact_kinds=(FactKind.RISK,),
                required=False,
                min_words=0,
                max_words=100,
                heading="Risks",
            ),
        ),
        compatible_modalities=("plain",),
        default_target_personas=("management",),
    )

    facts = [
        _fact("f001", FactKind.STATUS, "Service is green.", order=0, salience=1.3),
        _fact("f002", FactKind.METRIC, "Throughput reached 1000 rps.", order=1, salience=1.6),
        _fact("f003", FactKind.STATUS, "Secondary status is healthy.", order=2, salience=1.3),
        _fact("f004", FactKind.BACKGROUND, "Legacy context detail.", order=3, salience=1.0),
    ]

    plan = plan_structure(_model(facts), structure)
    by_name = {ps.section.name: ps.facts for ps in plan.sections}

    # Sorted by (-salience, order) and assigned once to the first matching section
    assert [f.id for f in by_name["primary"]] == ["f002", "f001", "f003"]
    assert by_name["overlap"] == ()
    assert by_name["risks"] == ()

    # Unmatched facts land in unused_facts in ascending order
    assert [f.id for f in plan.unused_facts] == ["f004"]

    # Missing required section and unused fact both produce warnings
    assert any("overlap" in w for w in plan.warnings)
    assert any("1 fact(s)" in w for w in plan.warnings)


@pytest.mark.parametrize(
    ("depth", "expected_cap"),
    [
        (DepthLevel.LOW, 1),
        (DepthLevel.MEDIUM, 3),
        (DepthLevel.HIGH, 6),
    ],
)
def test_adapt_depth_caps_and_ascending_source_order(
    depth: DepthLevel, expected_cap: int
) -> None:
    libs = load_libraries()
    structure = libs.structures["status_update"]
    # 8 progress facts with salience descending as order increases, except later facts have high salience
    facts = [
        _fact(f"f{i + 1:03d}", FactKind.PROGRESS, f"Completed task {i + 1}.", order=i, salience=1.0 + 0.1 * i)
        for i in range(8)
    ]
    facts.insert(0, _fact("f000", FactKind.STATUS, "Project is on track.", order=99, salience=1.3))
    plan = plan_structure(_model(facts), structure)

    source = _persona(pid="src", kind=PersonaKind.SOURCE)
    target = _persona(pid="tgt", kind=PersonaKind.TARGET, detail_depth=depth)

    adapted = adapt(plan, source, target, libs.glossary)
    progress = next(ps for ps in adapted.sections if ps.section.name == "progress")

    assert len(progress.facts) == expected_cap
    # Top salience facts kept, then re-ordered in ascending fact.order
    expected_orders = list(range(8 - expected_cap, 8))
    assert [f.order for f in progress.facts] == expected_orders
    assert any("progress" in w and str(8 - expected_cap) in w for w in adapted.warnings)


def test_adapt_source_keyword_boost_and_min_length_threshold() -> None:
    libs = load_libraries()
    structure = libs.structures["status_update"]

    # f001 has salience 1.2 (no keyword)
    # f002 has salience 1.0 + 0.3 boost from 'latency' (len 7 >= 4) => 1.3 > 1.2
    # f003 has salience 1.1 and mentions 'api' (len 3 < 4) => NO boost => 1.1 < 1.2
    facts = [
        _fact("f001", FactKind.PROGRESS, "Updated documentation pages.", order=0, salience=1.2),
        _fact("f002", FactKind.PROGRESS, "Reduced latency across edge nodes.", order=1, salience=1.0),
        _fact("f003", FactKind.PROGRESS, "Cleaned up api handlers.", order=2, salience=1.1),
    ]
    plan = plan_structure(_model(facts), structure)

    source = _persona(
        pid="dev",
        kind=PersonaKind.SOURCE,
        priorities=("latency", "api"),
    )
    target = _persona(
        pid="mgmt",
        kind=PersonaKind.TARGET,
        detail_depth=DepthLevel.LOW,  # cap = 1
    )

    adapted = adapt(plan, source, target, libs.glossary)
    progress = next(ps for ps in adapted.sections if ps.section.name == "progress")
    assert [f.id for f in progress.facts] == ["f002"]

    # Now verify len<4 keyword does not beat f001 when 'latency' is removed
    source_short_only = _persona(
        pid="dev_short",
        kind=PersonaKind.SOURCE,
        priorities=("api",),
    )
    adapted_short = adapt(plan, source_short_only, target, libs.glossary)
    progress_short = next(ps for ps in adapted_short.sections if ps.section.name == "progress")
    assert [f.id for f in progress_short.facts] == ["f001"]


def test_adapt_preserves_ascending_order_even_when_later_fact_boosted() -> None:
    libs = load_libraries()
    structure = libs.structures["status_update"]

    facts = [
        _fact("f001", FactKind.PROGRESS, "First milestone shipped.", order=2, salience=1.2),
        _fact("f002", FactKind.PROGRESS, "Unrelated cleanup.", order=5, salience=1.0),
        _fact("f003", FactKind.PROGRESS, "Fixed blocker in staging.", order=10, salience=1.05),
        _fact("f004", FactKind.PROGRESS, "Verified latency budget.", order=1, salience=1.0),
    ]
    plan = plan_structure(_model(facts), structure)
    source = _persona(
        pid="dev",
        kind=PersonaKind.SOURCE,
        priorities=("latency",),
        typical_concerns=("blocker",),
    )
    target = _persona(pid="po", kind=PersonaKind.TARGET, detail_depth=DepthLevel.MEDIUM)

    adapted = adapt(plan, source, target, libs.glossary)
    progress = next(ps for ps in adapted.sections if ps.section.name == "progress")
    # f003 (1.35), f004 (1.30), f001 (1.20) survive cap=3; f002 (1.0) dropped
    # Output order must be ascending fact.order: 1, 2, 10
    assert [f.id for f in progress.facts] == ["f004", "f001", "f003"]
    assert [f.order for f in progress.facts] == [1, 2, 10]


def test_adapt_reorders_sections_by_target_section_priority() -> None:
    libs = load_libraries()
    structure = libs.structures["status_update"]
    # Original order: status, progress, risks, next_steps, asks
    facts = [
        _fact("f001", FactKind.STATUS, "Status is green.", order=0),
        _fact("f002", FactKind.PROGRESS, "Shipped v1.", order=1),
        _fact("f003", FactKind.RISK, "Vendor risk remains.", order=2),
        _fact("f004", FactKind.NEXT_STEP, "Roll out next week.", order=3),
        _fact("f005", FactKind.ASK, "Please approve the launch.", order=4),
    ]
    plan = plan_structure(_model(facts), structure)
    source = libs.personas[(PersonaKind.SOURCE, "developer")]
    target = libs.personas[(PersonaKind.TARGET, "management")]
    # management.section_priority = ("status", "risks", "asks", "next_steps")

    adapted = adapt(plan, source, target, libs.glossary)
    assert [ps.section.name for ps in adapted.sections] == [
        "status",
        "risks",
        "asks",
        "next_steps",
        "progress",
    ]


@pytest.mark.parametrize(
    ("jargon_level", "expect_plain"),
    [
        (JargonLevel.LOW, True),
        (JargonLevel.MEDIUM, False),
        (JargonLevel.HIGH, False),
    ],
)
def test_adapt_glossary_substitutions_by_jargon_level(
    jargon_level: JargonLevel, expect_plain: bool
) -> None:
    libs = load_libraries()
    structure = libs.structures["status_update"]
    plan = plan_structure(
        _model([_fact("f001", FactKind.STATUS, "System is healthy.", order=0)]),
        structure,
    )
    glossary = Glossary(
        plain={"latency": "response time", "utilize": "plain-override"},
        preferred={"utilize": "use", "prior to": "before"},
        banned=("synergy",),
    )
    source = _persona(pid="src", kind=PersonaKind.SOURCE)
    target = _persona(pid="tgt", kind=PersonaKind.TARGET, jargon_level=jargon_level)

    adapted = adapt(plan, source, target, glossary)
    assert adapted.substitutions["utilize"] == "use"
    assert adapted.substitutions["prior to"] == "before"
    if expect_plain:
        assert adapted.substitutions["latency"] == "response time"
    else:
        assert "latency" not in adapted.substitutions


def test_adapt_cta_style_only_when_kept_ask_exists() -> None:
    libs = load_libraries()
    structure = libs.structures["decision_memo"]
    # decision_memo.asks accepts (FactKind.ASK, FactKind.NEXT_STEP)
    source = libs.personas[(PersonaKind.SOURCE, "developer")]  # (technical_review, direct)
    target = libs.personas[(PersonaKind.TARGET, "management")]  # (approval, direct), depth=LOW

    # Case 1: No ASK facts at all -> cta_style is None
    plan_no_ask = plan_structure(
        _model([
            _fact("f001", FactKind.STATUS, "Current state is healthy.", order=0),
            _fact("f002", FactKind.DECISION, "We decided to proceed.", order=1),
            _fact("f003", FactKind.NEXT_STEP, "Team will deploy Friday.", order=2),
        ]),
        structure,
    )
    adapted_no_ask = adapt(plan_no_ask, source, target, libs.glossary)
    assert adapted_no_ask.cta_style is None

    # Case 2: ASK fact exists in plan, but is dropped by LOW depth cap (1) behind higher-salience NEXT_STEP
    plan_dropped_ask = plan_structure(
        _model([
            _fact("f001", FactKind.STATUS, "Current state is healthy.", order=0),
            _fact("f002", FactKind.DECISION, "We decided to proceed.", order=1),
            _fact("f003", FactKind.NEXT_STEP, "Deploy 50% traffic Friday.", order=2, salience=1.8),
            _fact("f004", FactKind.ASK, "Please approve the rollout.", order=3, salience=1.0),
        ]),
        structure,
    )
    adapted_dropped_ask = adapt(plan_dropped_ask, source, target, libs.glossary)
    asks_sec = next(ps for ps in adapted_dropped_ask.sections if ps.section.name == "asks")
    assert [f.id for f in asks_sec.facts] == ["f003"]
    assert adapted_dropped_ask.cta_style is None

    # Case 3: ASK fact survives depth cap -> shared cta_style ("direct") chosen
    plan_kept_ask = plan_structure(
        _model([
            _fact("f001", FactKind.STATUS, "Current state is healthy.", order=0),
            _fact("f002", FactKind.DECISION, "We decided to proceed.", order=1),
            _fact("f003", FactKind.ASK, "Please approve the rollout.", order=2, salience=1.5),
        ]),
        structure,
    )
    adapted_kept_ask = adapt(plan_kept_ask, source, target, libs.glossary)
    assert adapted_kept_ask.cta_style == "direct"

    # Case 4: No shared cta_style -> target's first, else source's first, else None
    target_disjoint = _persona(pid="exec", kind=PersonaKind.TARGET, cta_styles=("approval", "decision"))
    assert adapt(plan_kept_ask, source, target_disjoint, libs.glossary).cta_style == "approval"

    target_empty_cta = _persona(pid="empty", kind=PersonaKind.TARGET, cta_styles=())
    assert adapt(plan_kept_ask, source, target_empty_cta, libs.glossary).cta_style == "technical_review"

    source_empty_cta = _persona(pid="src_empty", kind=PersonaKind.SOURCE, cta_styles=())
    assert adapt(plan_kept_ask, source_empty_cta, target_empty_cta, libs.glossary).cta_style is None
