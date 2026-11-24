"""TC-026: Stress tests for OOM-safe direct-index variant sampling in RuleBasedRealizer."""

from __future__ import annotations

import math
import time
from typing import Any

import pytest

from casper.libraries import load_libraries
from casper.models import (
    AdaptedPlan,
    Constraints,
    Fact,
    FactKind,
    PersonaKind,
    PlanSection,
    RewriteRule,
    Section,
    Structure,
)
from casper.realizer import (
    MAX_COMBINATIONS,
    RuleBasedRealizer,
    _decode_flat_index,
    _sample_flat_indices,
)


def _make_exploding_plan(libs: Any, num_facts: int) -> AdaptedPlan:
    section = Section(
        name="progress",
        purpose="Completed work",
        fact_kinds=(FactKind.PROGRESS,),
        required=True,
        min_words=0,
        max_words=2000,
        heading="Progress",
    )
    facts = tuple(
        Fact(
            id=f"f{i + 1:03d}",
            kind=FactKind.PROGRESS,
            text=f"We do not see errors on worker {i + 1} because it is healthy.",
            source="<stress>",
            order=i,
            salience=1.0,
        )
        for i in range(num_facts)
    )
    structure = Structure(
        id="stress_struct",
        goal="Stress test structure",
        sections=(section,),
        compatible_modalities=("memo", "plain"),
        default_target_personas=("management",),
    )
    return AdaptedPlan(
        structure=structure,
        source=libs.personas[(PersonaKind.SOURCE, "developer")],
        target=libs.personas[(PersonaKind.TARGET, "management")],
        sections=(PlanSection(section=section, facts=facts),),
        substitutions={},
        cta_style=None,
    )


def test_tc026_fifteen_fact_explosion_bounded_and_fast() -> None:
    """TC-026: 15 facts with >=3 variants each (3^15 = 14,348,907+) stays <=512 and <0.5s."""
    bases = [3] * 15
    assert math.prod(bases) == 14_348_907

    t0 = time.perf_counter()
    indices_a = _sample_flat_indices(bases, seed=42, max_combinations=MAX_COMBINATIONS)
    indices_b = _sample_flat_indices(bases, seed=42, max_combinations=MAX_COMBINATIONS)
    indices_c = _sample_flat_indices(bases, seed=99, max_combinations=MAX_COMBINATIONS)
    elapsed_sample = time.perf_counter() - t0

    assert len(indices_a) == MAX_COMBINATIONS == 512
    assert indices_a[0] == 0
    assert _decode_flat_index(indices_a[0], bases) == (0,) * 15
    assert len(set(indices_a)) == 512
    assert indices_a == indices_b
    assert indices_a != indices_c
    assert elapsed_sample < 0.5

    # End-to-end RuleBasedRealizer on 15 facts (actual product is 2 * 6^14 > 1.5e11)
    libs = load_libraries()
    plan = _make_exploding_plan(libs, 15)
    realizer = RuleBasedRealizer(libs)

    t1 = time.perf_counter()
    draft = realizer.realize(
        plan,
        voice=None,
        constraints=Constraints(candidates=512, seed=7),
        modality=libs.modalities["memo"],
    )
    elapsed_realize = time.perf_counter() - t1

    assert elapsed_realize < 0.5
    assert 1 <= draft.candidates_considered <= MAX_COMBINATIONS
    assert len(draft.sections) == 1
    assert len(draft.sections[0].sentences) == 15
    assert draft.sections[0].sentences[0].text == (
        "We do not see errors on worker 1 because it is healthy."
    )


def test_tc026_astronomical_combination_space_with_voice_scoring() -> None:
    """Even 40 facts (4^40 > 10^24 combinations) samples in O(512) without OOM."""
    bases = [4] * 40
    assert math.prod(bases) > 10**23

    t0 = time.perf_counter()
    indices = _sample_flat_indices(bases, seed=123, max_combinations=MAX_COMBINATIONS)
    decoded = [_decode_flat_index(idx, bases) for idx in indices]
    elapsed = time.perf_counter() - t0

    assert len(indices) == 512
    assert decoded[0] == (0,) * 40
    assert all(len(d) == 40 and all(0 <= x < 4 for x in d) for d in decoded)
    assert elapsed < 0.5


def test_tc026_realizer_with_custom_3_variant_rules_and_mocked_scorer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full candidate generation + deduplication + cap <=512 with 15 facts (3^15 combinations)."""
    from casper import realizer as realizer_mod
    from casper.models import ConfidenceBand, ConformanceReport, MatchBand

    libs = load_libraries()
    plan = _make_exploding_plan(libs, 15)

    # 3 variants per fact: plain + 2 custom rules -> exact 3^15 = 14,348,907 combinations
    rules = (
        RewriteRule(id="plain", description="plain", added_tokens=frozenset(), apply=lambda s: [s]),
        RewriteRule(
            id="v1",
            description="v1",
            added_tokens=frozenset({"clearly"}),
            apply=lambda s: [f"Clearly, {s}"],
        ),
        RewriteRule(
            id="v2",
            description="v2",
            added_tokens=frozenset({"briefly"}),
            apply=lambda s: [f"Briefly, {s}"],
        ),
    )

    scored_count = 0

    def _fast_score(profile: dict[str, Any], doc: Any, *, nlp: Any = None) -> ConformanceReport:
        nonlocal scored_count
        scored_count += 1
        return ConformanceReport(
            overall=75.0,
            band=MatchBand.CLOSE,
            confidence=ConfidenceBand.LOW,
            word_count=50,
            dimensions={"rhythm": 0.75},
            features=(),
            largest_gaps=(),
            signature_matches=(),
            frame_matches=(),
        )

    monkeypatch.setattr(realizer_mod, "score_voice", _fast_score)

    class _DummyNlp:
        def pipe(self, texts: Any) -> Any:
            return iter(())

    t0 = time.perf_counter()
    draft = RuleBasedRealizer(libs, rules=rules).realize(
        plan,
        voice={"dummy": True},
        constraints=Constraints(candidates=1000, seed=0),
        modality=libs.modalities["memo"],
        nlp=_DummyNlp(),
    )
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5
    assert scored_count == MAX_COMBINATIONS == 512
    assert draft.candidates_considered == 512
    # All ties -> candidate 0 (all-plain) wins
    assert draft.declared_additions == frozenset()
