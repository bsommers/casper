"""TC-013: Unit tests for RuleBasedRealizer, substitute, and fit_to_limits."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator
from typing import Any

import pytest

from casper.features import analyze
from casper.libraries import load_libraries
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
    MarkupKind,
    Modality,
    PersonaKind,
    PlanSection,
    RewriteRule,
    Section,
    Sentence,
    Structure,
)
from casper.parsing import load_nlp
from casper.realizer import RuleBasedRealizer, fit_to_limits, substitute
from casper.rewrites import (
    ALLOWED_RULE_TOKENS,
    REWRITE_RULES,
    apply_transition_opener_with_names,
    merge_pair_semicolon,
)


@pytest.fixture(scope="module")
def nlp() -> Any:
    return load_nlp(ner=False)


@pytest.fixture(scope="module")
def libs() -> Any:
    return load_libraries()


@pytest.fixture(scope="module")
def base_profile(nlp: Any) -> dict[str, Any]:
    docs = [
        Document(
            source="s1.md",
            format="markdown",
            blocks=(
                Block(kind=BlockKind.HEADING, text="Status", level=2),
                Block(
                    kind=BlockKind.PARAGRAPH,
                    text=(
                        "We build reliable tools for small teams. It isn't complicated; "
                        "we test every release carefully. We don't ship untested code."
                    ),
                ),
            ),
        ),
        Document(
            source="s2.md",
            format="markdown",
            blocks=(
                Block(kind=BlockKind.HEADING, text="Next Steps", level=2),
                Block(
                    kind=BlockKind.PARAGRAPH,
                    text=(
                        "Also, we keep changes small and focused. We can't guess when "
                        "metrics tell the story; we measure first."
                    ),
                ),
            ),
        ),
    ]
    feats = analyze(docs, nlp=nlp)
    total_words = int(feats["lexical"]["words"])
    return {
        "schema_version": 1,
        "author": {"id": "tester", "display_name": "Tester", "aliases": []},
        "corpus": {
            "document_count": len(docs),
            "total_words": total_words,
            "avg_doc_words": round(total_words / len(docs), 2),
        },
        **feats,
    }


def _make_fact(
    fid: str,
    text: str,
    *,
    kind: FactKind = FactKind.PROGRESS,
    order: int = 0,
    salience: float = 1.0,
    entities: tuple[str, ...] = (),
    owners: tuple[str, ...] = (),
) -> Fact:
    return Fact(
        id=fid,
        kind=kind,
        text=text,
        source="<inline>",
        order=order,
        salience=salience,
        entities=entities,
        owners=owners,
    )


def _make_adapted_plan(
    libs: Any,
    sections: tuple[PlanSection, ...],
    *,
    substitutions: dict[str, str] | None = None,
    cta_style: str | None = None,
    warnings: tuple[str, ...] = (),
) -> AdaptedPlan:
    structure = Structure(
        id="test_struct",
        goal="Test structure",
        sections=tuple(ps.section for ps in sections),
        compatible_modalities=("plain", "memo", "slack", "article"),
        default_target_personas=("management",),
    )
    return AdaptedPlan(
        structure=structure,
        source=libs.personas[(PersonaKind.SOURCE, "developer")],
        target=libs.personas[(PersonaKind.TARGET, "management")],
        sections=sections,
        substitutions=substitutions if substitutions is not None else {},
        cta_style=cta_style,
        warnings=warnings,
    )


def _section(name: str, *, required: bool = False, heading: str | None = None) -> Section:
    return Section(
        name=name,
        purpose=f"Purpose of {name}",
        fact_kinds=(FactKind.STATUS, FactKind.PROGRESS, FactKind.ASK),
        required=required,
        min_words=0,
        max_words=200,
        heading=heading or name.title(),
    )


class TestSubstitute:
    def test_whole_word_case_preserving_and_longest_first(self) -> None:
        mapping = {
            "in": "inside",
            "in order to": "to",
            "latency": "response time",
            "utilize": "use",
        }
        assert substitute("LATENCY dropped.", mapping) == "RESPONSE TIME dropped."
        assert substitute("Latency dropped.", mapping) == "Response time dropped."
        assert substitute("The latency dropped.", mapping) == "The response time dropped."
        assert substitute("In order to ship fast.", mapping) == "To ship fast."
        assert substitute("IN ORDER TO ship.", mapping) == "TO ship."
        assert substitute("superlatency and latency_ms stay intact.", mapping) == (
            "superlatency and latency_ms stay intact."
        )
        assert substitute("(latency)!", mapping) == "(response time)!"

    def test_single_pass_never_resubstitutes(self) -> None:
        mapping = {"alpha": "beta", "beta": "gamma"}
        assert substitute("alpha and beta", mapping) == "beta and gamma"

    def test_edge_cases_empty_and_duplicate_case_keys(self) -> None:
        assert substitute("", {"a": "b"}) == ""
        assert substitute("hello", {}) == "hello"
        assert substitute("hello", {"": "x"}) == "hello"
        assert substitute("Drop it.", {"drop": ""}) == " it."
        # Duplicate keys differing only by case resolve deterministically
        assert substitute("Foo foo", {"Foo": "bar", "foo": "baz"}) == "Bar bar"


class TestFitToLimits:
    def test_exact_word_and_char_boundaries_including_html(self, libs: Any) -> None:
        sec_req = _section("status", required=True, heading="Status")
        sec_opt = _section("progress", required=False, heading="Progress")
        f1 = _make_fact("f001", "Core service stays healthy.", kind=FactKind.STATUS, salience=1.5)
        f2 = _make_fact("f002", "We shipped parser updates.", kind=FactKind.PROGRESS, salience=1.0)
        plan = _make_adapted_plan(
            libs,
            (
                PlanSection(section=sec_req, facts=(f1,)),
                PlanSection(section=sec_opt, facts=(f2,)),
            ),
        )
        draft = Draft(
            title="Weekly Update",
            sections=(
                DraftSection(
                    name="status",
                    heading="Status",
                    sentences=(Sentence(text=f1.text, fact_ids=("f001",)),),
                ),
                DraftSection(
                    name="progress",
                    heading="Progress",
                    sentences=(Sentence(text=f2.text, fact_ids=("f002",)),),
                ),
            ),
            declared_additions=frozenset({"also"}),
            candidates_considered=4,
            backend=BackendKind.RULES,
            meta={"k": "v"},
        )
        html_mod = libs.modalities["article"]
        words, chars = count_rendered(draft, html_mod)

        # At exact boundary (max_words, max_chars) -> untouched
        same_w = fit_to_limits(draft, plan, Constraints(max_words=words, max_chars=chars), html_mod)
        assert same_w == draft
        assert same_w.warnings == ()

        # At max_words + 1 (i.e. limit = words - 1) -> trims optional sentence
        trimmed_w = fit_to_limits(draft, plan, Constraints(max_words=words - 1), html_mod)
        assert len(trimmed_w.sections) == 1
        assert trimmed_w.sections[0].name == "status"
        assert count_rendered(trimmed_w, html_mod)[0] <= words - 1
        assert trimmed_w.declared_additions == frozenset({"also"})
        assert trimmed_w.title == "Weekly Update"
        assert trimmed_w.candidates_considered == 4
        assert trimmed_w.meta == {"k": "v"}
        assert any("Trimmed 1" in w for w in trimmed_w.warnings)

        # At max_chars - 1 (HTML tags count toward chars) -> trims optional sentence
        trimmed_c = fit_to_limits(draft, plan, Constraints(max_chars=chars - 1), html_mod)
        assert len(trimmed_c.sections) == 1
        assert count_rendered(trimmed_c, html_mod)[1] <= chars - 1

    def test_salience_ordering_tie_break_and_required_protection(self, libs: Any) -> None:
        sec_req = _section("status", required=True, heading="Status")
        sec_opt = _section("progress", required=False, heading="Progress")
        f_req_low = _make_fact("f001", "Required anchor fact.", kind=FactKind.STATUS, salience=0.5)
        f_req_second = _make_fact(
            "f002", "Second required sentence.", kind=FactKind.STATUS, salience=1.0
        )
        f_opt_1 = _make_fact("f003", "Optional first sentence.", kind=FactKind.PROGRESS, salience=1.0)
        f_opt_2 = _make_fact(
            "f004", "Optional second sentence.", kind=FactKind.PROGRESS, salience=1.0
        )
        plan = _make_adapted_plan(
            libs,
            (
                PlanSection(section=sec_req, facts=(f_req_low, f_req_second)),
                PlanSection(section=sec_opt, facts=(f_opt_1, f_opt_2)),
            ),
        )
        draft = Draft(
            sections=(
                DraftSection(
                    name="status",
                    heading="Status",
                    sentences=(
                        Sentence(text=f_req_low.text, fact_ids=("f001",)),
                        Sentence(text=f_req_second.text, fact_ids=("f002",)),
                    ),
                ),
                DraftSection(
                    name="progress",
                    heading="Progress",
                    sentences=(
                        Sentence(text=f_opt_1.text, fact_ids=("f003",)),
                        Sentence(text=f_opt_2.text, fact_ids=("f004",)),
                    ),
                ),
            )
        )
        plain_mod = libs.modalities["plain"]
        # Drop exactly 1 sentence: equal salience 1.0 -> drops last sentence f004 first
        total_words, _ = count_rendered(draft, plain_mod)
        one_dropped = fit_to_limits(draft, plan, Constraints(max_words=total_words - 1), plain_mod)
        kept_ids = [fid for sec in one_dropped.sections for s in sec.sentences for fid in s.fact_ids]
        assert kept_ids == ["f001", "f002", "f003"]

        # Impossible tight limit -> drops all droppable sentences, protects f001, records warning
        protected_only = fit_to_limits(draft, plan, Constraints(max_words=1), plain_mod)
        kept_ids_min = [
            fid for sec in protected_only.sections for s in sec.sentences for fid in s.fact_ids
        ]
        assert kept_ids_min == ["f001"]
        assert any("protected" in w for w in protected_only.warnings)

    def test_drops_closing_frame_when_last_ask_trimmed(self, libs: Any) -> None:
        sec_req = _section("status", required=True, heading="Status")
        sec_ask = _section("asks", required=False, heading="Asks")
        f_status = _make_fact("f001", "Service is green.", kind=FactKind.STATUS, salience=1.8)
        f_ask = _make_fact("f002", "Please approve budget.", kind=FactKind.ASK, salience=1.0)
        plan = _make_adapted_plan(
            libs,
            (
                PlanSection(section=sec_req, facts=(f_status,)),
                PlanSection(section=sec_ask, facts=(f_ask,)),
            ),
            cta_style="approval",
        )
        draft = Draft(
            sections=(
                DraftSection(
                    name="status",
                    heading="Status",
                    sentences=(Sentence(text=f_status.text, fact_ids=("f001",)),),
                ),
                DraftSection(
                    name="asks",
                    heading="Asks",
                    sentences=(
                        Sentence(text=f_ask.text, fact_ids=("f002",)),
                        Sentence(
                            text="Please let me know if you approve.",
                            fact_ids=(),
                            frame=True,
                        ),
                    ),
                ),
            )
        )
        plain_mod = libs.modalities["plain"]
        trimmed = fit_to_limits(draft, plan, Constraints(max_words=4), plain_mod)
        assert len(trimmed.sections) == 1
        assert trimmed.sections[0].name == "status"
        assert all(not s.frame for sec in trimmed.sections for s in sec.sentences)

    def test_falls_back_to_modality_limits_when_constraints_none(self, libs: Any) -> None:
        tiny_mod = Modality(
            id="tiny",
            markup=MarkupKind.PLAIN,
            max_words=3,
            max_chars=500,
            title=False,
            headings="none",
            bullets=False,
            description="Tiny modality",
        )
        sec = _section("progress", required=False)
        f1 = _make_fact("f001", "Alpha beta gamma.", salience=1.5)
        f2 = _make_fact("f002", "Delta epsilon zeta.", salience=1.0)
        plan = _make_adapted_plan(libs, (PlanSection(section=sec, facts=(f1, f2)),))
        draft = Draft(
            sections=(
                DraftSection(
                    name="progress",
                    heading="Progress",
                    sentences=(
                        Sentence(text=f1.text, fact_ids=("f001",)),
                        Sentence(text=f2.text, fact_ids=("f002",)),
                    ),
                ),
            )
        )
        trimmed = fit_to_limits(draft, plan, Constraints(), tiny_mod)
        assert count_rendered(trimmed, tiny_mod)[0] == 3
        assert [s.fact_ids for s in trimmed.sections[0].sentences] == [("f001",)]


class TestRuleBasedRealizer:
    def test_voice_none_skips_spacy_and_applies_substitutions_and_cta(self, libs: Any) -> None:
        class _FailNlp:
            def __call__(self, text: str) -> Any:
                raise AssertionError("spaCy should not be invoked when voice is None")

            def pipe(self, texts: Iterable[str], *args: Any, **kwargs: Any) -> Iterator[Any]:
                raise AssertionError("spaCy pipe should not be invoked when voice is None")

        sec = _section("asks", required=True, heading="Asks")
        f1 = _make_fact(
            "f001",
            "We utilize caches in order to reduce latency.",
            kind=FactKind.ASK,
            order=0,
        )
        plan = _make_adapted_plan(
            libs,
            (PlanSection(section=sec, facts=(f1,)),),
            substitutions={"utilize": "use", "in order to": "to", "latency": "response time"},
            cta_style="approval",
            warnings=("plan-note",),
        )
        realizer = RuleBasedRealizer(libs)
        draft_s0 = realizer.realize(
            plan,
            voice=None,
            constraints=Constraints(seed=0, candidates=8),
            modality=libs.modalities["memo"],
            nlp=_FailNlp(),
        )
        assert draft_s0.backend == BackendKind.RULES
        assert draft_s0.candidates_considered == 1
        assert draft_s0.declared_additions == frozenset()
        assert "plan-note" in draft_s0.warnings
        sents = draft_s0.sections[0].sentences
        assert sents[0].text == "We use caches to reduce response time."
        assert sents[0].fact_ids == ("f001",)
        assert sents[1].frame is True
        assert sents[1].fact_ids == ()
        assert sents[1].text == libs.phrasebank["approval"][0]

        # seed=1 selects second phrase deterministically
        draft_s1 = realizer.realize(
            plan,
            voice=None,
            constraints=Constraints(seed=1, candidates=8),
            modality=libs.modalities["memo"],
            nlp=_FailNlp(),
        )
        assert draft_s1.sections[0].sentences[1].text == libs.phrasebank["approval"][1]

    def test_empty_plan_returns_empty_draft(self, libs: Any) -> None:
        sec = _section("status", required=True)
        plan = _make_adapted_plan(libs, (PlanSection(section=sec, facts=()),))
        draft = RuleBasedRealizer(libs).realize(
            plan,
            voice=None,
            constraints=Constraints(),
            modality=libs.modalities["plain"],
        )
        assert draft.sections == ()
        assert draft.candidates_considered == 1
        assert draft.declared_additions == frozenset()

    def test_unknown_cta_style_omits_frame(self, libs: Any) -> None:
        sec = _section("asks", required=True)
        f1 = _make_fact("f001", "Please confirm the timeline.", kind=FactKind.ASK)
        plan = _make_adapted_plan(
            libs,
            (PlanSection(section=sec, facts=(f1,)),),
            cta_style="nonexistent_style",
        )
        draft = RuleBasedRealizer(libs).realize(
            plan,
            voice=None,
            constraints=Constraints(),
            modality=libs.modalities["plain"],
        )
        assert len(draft.sections[0].sentences) == 1
        assert draft.sections[0].sentences[0].frame is False

    def test_voice_ranking_declared_additions_and_parse_cache(
        self,
        libs: Any,
        base_profile: dict[str, Any],
        nlp: Any,
    ) -> None:
        class _CountingNlp:
            def __init__(self, inner: Any) -> None:
                self._inner = inner
                self.parsed_texts: list[str] = []

            def __call__(self, text: str) -> Any:
                self.parsed_texts.append(text)
                return self._inner(text)

            def pipe(self, texts: Iterable[str], *args: Any, **kwargs: Any) -> Iterator[Any]:
                items = list(texts)
                self.parsed_texts.extend(items)
                yield from self._inner.pipe(items, *args, **kwargs)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        # Pin high contractions_per_1k and zero semicolons so contracted variant outscores plain/merge
        profile = copy.deepcopy(base_profile)
        profile["pins"] = {
            "contractions_per_1k": {"value": 120.0, "stdev": 5.0},
            "semicolons_per_1k": {"value": 0.0, "stdev": 1.0},
            "mean_sentence_length": {"value": 4.5, "stdev": 1.0},
        }

        sec1 = _section("status", required=True, heading="Status")
        sec2 = _section("progress", required=False, heading="Progress")
        f1 = _make_fact("f001", "We do not have blockers.", kind=FactKind.STATUS, order=0)
        f2 = _make_fact("f002", "It is ready for rollout.", kind=FactKind.PROGRESS, order=1)
        f3 = _make_fact(
            "f003",
            "Alice verified the dashboard.",
            kind=FactKind.PROGRESS,
            order=2,
            owners=("Alice",),
        )
        plan = _make_adapted_plan(
            libs,
            (
                PlanSection(section=sec1, facts=(f1,)),
                PlanSection(section=sec2, facts=(f2, f3)),
            ),
        )
        counting = _CountingNlp(nlp)
        realizer = RuleBasedRealizer(libs)
        draft = realizer.realize(
            plan,
            voice=profile,
            constraints=Constraints(candidates=8, seed=0),
            modality=libs.modalities["memo"],
            nlp=counting,
        )
        assert 2 <= draft.candidates_considered <= 8
        assert draft.declared_additions <= ALLOWED_RULE_TOKENS
        rendered = format_draft(draft, libs.modalities["memo"])
        assert "don't" in rendered or "It's" in rendered
        assert draft.declared_additions & {"don't", "it's"}
        # Parse cache guarantees each distinct prose text parsed at most once
        assert len(counting.parsed_texts) == len(set(counting.parsed_texts))

        # Determinism check
        draft2 = realizer.realize(
            plan,
            voice=profile,
            constraints=Constraints(candidates=8, seed=0),
            modality=libs.modalities["memo"],
            nlp=nlp,
        )
        assert draft == draft2

    def test_semicolon_merge_preserves_proper_nouns_and_fact_ids(
        self,
        libs: Any,
        base_profile: dict[str, Any],
        nlp: Any,
    ) -> None:
        # Pin semicolons and single-sentence paragraph shape so merged candidate strongly outscores plain
        profile = copy.deepcopy(base_profile)
        profile["pins"] = {
            "semicolons_per_1k": {"value": 150.0, "stdev": 5.0},
            "mean_sentence_length": {"value": 7.0, "stdev": 1.0},
            "sentences_per_paragraph": {"value": 1.0, "stdev": 0.2},
            "single_sentence_paragraph_rate": {"value": 1.0, "stdev": 0.05},
        }
        sec = _section("progress", required=True, heading="Progress")
        f1 = _make_fact("f001", "The parser passed.", order=0)
        f2 = _make_fact(
            "f002",
            "Alice deployed API updates.",
            order=1,
            entities=("API",),
            owners=("Alice",),
        )
        plan = _make_adapted_plan(libs, (PlanSection(section=sec, facts=(f1, f2)),))
        # Restrict rules to plain + semicolon_merge to isolate merge behavior cleanly
        subset_rules = tuple(r for r in REWRITE_RULES if r.id in {"plain", "semicolon_merge"})
        draft = RuleBasedRealizer(libs, rules=subset_rules).realize(
            plan,
            voice=profile,
            constraints=Constraints(candidates=4, seed=0),
            modality=libs.modalities["plain"],
            nlp=nlp,
        )
        assert draft.candidates_considered == 2
        merged_sent = draft.sections[0].sentences[0]
        assert merged_sent.text == "The parser passed; Alice deployed API updates."
        assert merged_sent.fact_ids == ("f001", "f002")
        assert merged_sent.frame is False
        assert draft.declared_additions == frozenset()

    def test_transition_opener_only_non_initial_and_preserves_protected_names(
        self,
        libs: Any,
        base_profile: dict[str, Any],
        nlp: Any,
    ) -> None:
        profile = copy.deepcopy(base_profile)
        profile["pins"] = {
            "transition_start_rate": {"value": 0.9, "stdev": 0.05},
            "transitions_per_1k": {"value": 120.0, "stdev": 5.0},
        }
        sec = _section("progress", required=True, heading="Progress")
        f1 = _make_fact("f001", "The build succeeded.", order=0)
        f2 = _make_fact("f002", "Alice fixed the cache.", order=1, owners=("Alice",))
        plan = _make_adapted_plan(libs, (PlanSection(section=sec, facts=(f1, f2)),))
        subset_rules = tuple(r for r in REWRITE_RULES if r.id in {"plain", "transition_opener"})
        draft = RuleBasedRealizer(libs, rules=subset_rules).realize(
            plan,
            voice=profile,
            constraints=Constraints(candidates=8, seed=0),
            modality=libs.modalities["memo"],
            nlp=nlp,
        )
        sents = draft.sections[0].sentences
        # First sentence never gets a transition opener
        assert sents[0].text == "The build succeeded."
        # Second sentence gets transition opener while preserving proper noun "Alice"
        assert "Alice fixed the cache." in sents[1].text
        assert any(
            sents[1].text.startswith(op) for op in ("Also, ", "Next, ", "Additionally, ", "Finally, ")
        )
        assert len(draft.declared_additions) == 1
        assert draft.declared_additions <= ALLOWED_RULE_TOKENS

    def test_custom_rewrite_rule_and_unscorable_prose_fallback(
        self,
        libs: Any,
        base_profile: dict[str, Any],
        nlp: Any,
    ) -> None:
        custom_rule = RewriteRule(
            id="note_prefix",
            description="Prepend 'Notably,'",
            added_tokens=frozenset({"notably"}),
            apply=lambda s: [f"Notably, {s[0].lower()}{s[1:]}" if s else s],
        )
        sec = _section("status", required=True)
        f1 = _make_fact("f001", "Latency stayed steady.", kind=FactKind.STATUS)
        plan = _make_adapted_plan(libs, (PlanSection(section=sec, facts=(f1,)),))
        profile = copy.deepcopy(base_profile)
        profile["pins"] = {"mean_sentence_length": {"value": 4.0, "stdev": 0.2}}
        draft = RuleBasedRealizer(libs, rules=(REWRITE_RULES[0], custom_rule)).realize(
            plan,
            voice=profile,
            constraints=Constraints(candidates=4, seed=0),
            modality=libs.modalities["plain"],
            nlp=nlp,
        )
        assert draft.candidates_considered == 2
        if draft.sections[0].sentences[0].text.startswith("Notably,"):
            assert draft.declared_additions == frozenset({"notably"})

        # Unscorable candidate prose (pure punctuation) falls back gracefully to candidate 0
        punct_fact = _make_fact("f001", "---", kind=FactKind.STATUS)
        punct_plan = _make_adapted_plan(libs, (PlanSection(section=sec, facts=(punct_fact,)),))
        punct_draft = RuleBasedRealizer(libs).realize(
            punct_plan,
            voice=profile,
            constraints=Constraints(candidates=2, seed=0),
            modality=libs.modalities["plain"],
            nlp=nlp,
        )
        assert punct_draft.sections[0].sentences[0].text == "---"



class TestRewriteRulesDirect:
    @staticmethod
    def _rule_by_id(rule_id: str) -> RewriteRule:
        return next(rule for rule in REWRITE_RULES if rule.id == rule_id)

    @pytest.mark.parametrize(
        ("full_form", "contraction"),
        [
            ("do not", "don't"),
            ("cannot", "can't"),
            ("will not", "won't"),
            ("it is", "it's"),
            ("we are", "we're"),
            ("they are", "they're"),
            ("is not", "isn't"),
            ("are not", "aren't"),
            ("have not", "haven't"),
            ("has not", "hasn't"),
            ("does not", "doesn't"),
            ("did not", "didn't"),
        ],
    )
    def test_contract_and_expand_all_pairs_and_case(
        self,
        full_form: str,
        contraction: str,
    ) -> None:
        contract_rule = self._rule_by_id("contract")
        expand_rule = self._rule_by_id("expand")

        # Lowercase round-trip
        sent_full = f"Clearly {full_form} fail."
        contracted = contract_rule.apply(sent_full)
        assert contracted == [f"Clearly {contraction} fail."]
        assert expand_rule.apply(contracted[0]) == [sent_full]

        # Titlecase preservation
        sent_title = f"{full_form.capitalize()} ready."
        contracted_title = contract_rule.apply(sent_title)
        assert contracted_title == [f"{contraction.capitalize()} ready."]
        assert expand_rule.apply(contracted_title[0]) == [sent_title]

        # UPPERCASE preservation
        sent_upper = f"{full_form.upper()} READY."
        contracted_upper = contract_rule.apply(sent_upper)
        assert contracted_upper == [f"{contraction.upper()} READY."]
        assert expand_rule.apply(contracted_upper[0]) == [sent_upper]

        # No-op returns []
        assert contract_rule.apply("Plain steady sentence.") == []
        assert expand_rule.apply("Plain steady sentence.") == []

    def test_plain_and_transition_opener_rules(self) -> None:
        plain_rule = self._rule_by_id("plain")
        assert plain_rule.apply("Keep this exact.") == ["Keep this exact."]

        transition_rule = self._rule_by_id("transition_opener")
        assert transition_rule.apply("") == []
        assert transition_rule.apply("   ") == []
        assert transition_rule.apply("However, latency fell.") == []
        assert transition_rule.apply("Also, checks passed.") == []

        openers = transition_rule.apply("Latency fell.")
        assert openers == [
            "Also, Latency fell.",
            "Next, Latency fell.",
            "Additionally, Latency fell.",
            "Finally, Latency fell.",
        ]

        # Protected proper noun preserved when lowering initial word via apply_transition_opener_with_names
        protected_openers = apply_transition_opener_with_names(
            "Alice shipped the release.",
            protected_names=("Alice",),
        )
        assert protected_openers[0] == "Also, Alice shipped the release."
        unprotected_openers = apply_transition_opener_with_names("Latency fell.")
        assert unprotected_openers[0] == "Also, latency fell."
        assert apply_transition_opener_with_names("") == []
        assert apply_transition_opener_with_names("Finally, we shipped.") == []

    def test_semicolon_merge_rule_and_pair_helper(self) -> None:
        semicolon_rule = self._rule_by_id("semicolon_merge")
        # Per-sentence apply always returns [] (even on 1 sentence)
        assert semicolon_rule.apply("One short sentence.") == []

        # Merges two short sentences
        merged = merge_pair_semicolon("The parser passed.", "The tests stayed green.")
        assert merged == "The parser passed; the tests stayed green."

        # Skips when second starts with a transition word
        assert merge_pair_semicolon("Tests passed.", "However, memory rose.") is None
        assert merge_pair_semicolon("Tests passed.", "Next, we deploy.") is None

        # Skips when either sentence exceeds 12 words
        thirteen_words = "One two three four five six seven eight nine ten eleven twelve thirteen."
        assert merge_pair_semicolon(thirteen_words, "Short sentence.") is None
        assert merge_pair_semicolon("Short sentence.", thirteen_words) is None

        # Skips empty or question/exclamation first sentence
        assert merge_pair_semicolon("", "Short.") is None
        assert merge_pair_semicolon("Did it pass?", "Yes, it did.") is None

        # Preserves proper nouns, acronyms, and "I"
        assert (
            merge_pair_semicolon("Checks ran.", "Alice updated the docs.", protected_names=("Alice",))
            == "Checks ran; Alice updated the docs."
        )
        assert merge_pair_semicolon("Checks ran.", "API latency dropped.") == (
            "Checks ran; API latency dropped."
        )
        assert merge_pair_semicolon("Checks ran.", "I verified the build.") == (
            "Checks ran; I verified the build."
        )
