"""TC-011 & TC-020: Unit tests for fact ingestion, classification, salience, and NetworkX graph."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import networkx as nx
import pytest

from casper.errors import InputError
from casper.facts import ingest
from casper.models import FactKind
from casper.parsing import load_nlp

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def nlp_ner() -> object:
    return load_nlp(ner=True)


def test_ingest_status_notes_key_value_and_annotations(nlp_ner: object) -> None:
    model = ingest([FIXTURES / "status_notes.md"], nlp=nlp_ner)
    assert len(model.facts) == 9
    assert [f.id for f in model.facts] == [f"f{i:03d}" for i in range(1, 10)]
    assert [f.order for f in model.facts] == list(range(9))

    expected_kinds = [
        FactKind.STATUS,
        FactKind.DETAIL,
        FactKind.PROGRESS,
        FactKind.RISK,
        FactKind.NEXT_STEP,
        FactKind.DECISION,
        FactKind.ASK,
        FactKind.BACKGROUND,
        FactKind.METRIC,
    ]
    assert [f.kind for f in model.facts] == expected_kinds
    assert all(f.classification_source == "key" for f in model.facts)

    # Explicit Owner key populates owners and restates using only source words
    owner_fact = model.facts[1]
    assert owner_fact.text == "The owner is Priya Nair."
    assert "Priya Nair" in owner_fact.owners

    # Metrics and dates extracted accurately
    metric_fact = model.facts[8]
    assert "+6.4%" in metric_fact.metrics
    assert "94.2%" in metric_fact.metrics
    assert "$18,400" in metric_fact.metrics

    next_fact = model.facts[4]
    assert "2026-11-24" in next_fact.dates

    # Digest matches canonical JSON of facts
    expected_digest = hashlib.sha256(
        json.dumps(
            [f.to_dict() for f in model.facts],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert model.digest == expected_digest
    assert str(FIXTURES / "status_notes.md") in model.input_hashes


def test_ingest_inline_tags_precedence_over_headings_and_cues(nlp_ner: object) -> None:
    notes = (
        "## Progress\n\n"
        "[risk] Canary deployment is on track for Friday.\n\n"
        "[ask] Check the dashboard numbers.\n"
    )
    model = ingest(notes=notes, nlp=nlp_ner)
    assert len(model.facts) == 2
    assert model.facts[0].kind == FactKind.RISK
    assert model.facts[0].classification_source == "inline_tag"
    assert model.facts[0].text == "Canary deployment is on track for Friday."
    assert not model.facts[0].text.startswith("[")

    assert model.facts[1].kind == FactKind.ASK
    assert model.facts[1].classification_source == "inline_tag"
    assert model.facts[1].text == "Check the dashboard numbers."


def test_ingest_key_value_fragment_restatement(nlp_ner: object) -> None:
    notes = "Status: on track\nOwner: Elena Park\nMetric: 99.95% uptime\n"
    model = ingest(notes=notes, nlp=nlp_ner)
    assert [f.text for f in model.facts] == [
        "The status is on track.",
        "The owner is Elena Park.",
        "The metric is 99.95% uptime.",
    ]
    assert [f.kind for f in model.facts] == [
        FactKind.STATUS,
        FactKind.DETAIL,
        FactKind.METRIC,
    ]
    assert "Elena Park" in model.facts[1].owners
    assert "99.95%" in model.facts[2].metrics


def test_ingest_heading_classification_and_defaults(nlp_ner: object) -> None:
    notes = (
        "The platform serves regional caches worldwide.\n\n"
        "A second intro note with no special keywords.\n\n"
        "## Risks & Limitations\n"
        "Cache warmups take extra memory.\n\n"
        "## Decisions\n"
        "Use dual-stack routing for the rollout.\n\n"
        "## Benchmarks\n"
        "Tail latency sits near the baseline.\n\n"
        "## Approvals\n"
        "Sign-off from finance is needed by Monday.\n"
    )
    model = ingest(notes=notes, nlp=nlp_ner)
    assert [f.kind for f in model.facts] == [
        FactKind.BACKGROUND,  # paragraph 0 with no heading
        FactKind.DETAIL,      # paragraph 1 with no heading or cue
        FactKind.RISK,
        FactKind.DECISION,
        FactKind.METRIC,
        FactKind.ASK,
    ]
    assert [f.classification_source for f in model.facts] == [
        "default",
        "default",
        "heading",
        "heading",
        "heading",
        "heading",
    ]


def test_tc020_review_alone_is_not_ask_vs_explicit_ask(nlp_ner: object) -> None:
    model = ingest(
        notes=(
            "The team will review the plan.\n\n"
            "Please review and approve the plan.\n"
        ),
        nlp=nlp_ner,
    )
    assert len(model.facts) == 2
    first, second = model.facts
    assert first.kind != FactKind.ASK
    assert first.kind == FactKind.NEXT_STEP
    assert first.classification_source == "cue"

    assert second.kind == FactKind.ASK
    assert second.classification_source == "cue"


def test_ingest_cues_priority_order(nlp_ner: object) -> None:
    notes = (
        "Intro sentence without heading or cues.\n\n"
        "Latency regressed during the incident yesterday.\n\n"
        "We decided to keep the fallback route.\n\n"
        "We shipped the edge worker update.\n\n"
        "We plan to cut over next week.\n\n"
        "The rollout is on track.\n\n"
        "Throughput hit 450 rps at $120 daily cost.\n"
    )
    model = ingest(notes=notes, nlp=nlp_ner)
    kinds = [f.kind for f in model.facts]
    assert kinds == [
        FactKind.BACKGROUND,
        FactKind.RISK,
        FactKind.DECISION,
        FactKind.PROGRESS,
        FactKind.NEXT_STEP,
        FactKind.STATUS,
        FactKind.METRIC,
    ]
    assert all(f.classification_source == "cue" for f in model.facts[1:])


def test_ingest_csv_and_yaml_fixtures(nlp_ner: object) -> None:
    csv_model = ingest([FIXTURES / "sample.csv"], nlp=nlp_ner)
    assert len(csv_model.facts) == 6
    assert [f.kind for f in csv_model.facts] == [
        FactKind.STATUS,
        FactKind.DETAIL,
        FactKind.METRIC,
        FactKind.STATUS,
        FactKind.DETAIL,
        FactKind.METRIC,
    ]
    assert "Elena Park" in csv_model.facts[1].owners
    assert "99.95%" in csv_model.facts[2].metrics
    assert "Marcus Vance" in csv_model.facts[4].owners
    assert "42ms" in csv_model.facts[5].metrics

    yaml_model = ingest([FIXTURES / "sample.yaml"], nlp=nlp_ner)
    kinds_by_text = {f.text: f.kind for f in yaml_model.facts}
    assert any(k == FactKind.STATUS for k in kinds_by_text.values())
    assert any(k == FactKind.RISK for k in kinds_by_text.values())
    assert any(k == FactKind.NEXT_STEP for k in kinds_by_text.values())
    assert any("Elena Park" in f.owners for f in yaml_model.facts)
    assert any("2026-11-28" in f.dates for f in yaml_model.facts)


def test_deduplication_before_id_assignment(nlp_ner: object) -> None:
    notes = (
        "Cache rollout is on track.\n\n"
        "  cache   rollout is on track!\n\n"
        "Please approve the release window.\n"
    )
    model = ingest(notes=notes, nlp=nlp_ner)
    assert len(model.facts) == 2
    assert [f.id for f in model.facts] == ["f001", "f002"]
    assert all(re.match(r"^f\d{3,}$", f.id) for f in model.facts)
    assert model.facts[0].text == "Cache rollout is on track."
    assert model.facts[1].text == "Please approve the release window."


def test_salience_formula_and_fact_overrides(nlp_ner: object) -> None:
    notes = (
        "Acme Corp in Seattle improved latency by 25% on 2026-11-24.\n\n"
        "Simple detail note.\n"
    )
    base = ingest(notes=notes, nlp=nlp_ner)
    f1, f2 = base.facts
    expected_f1 = round(
        1.0
        + 0.4 * bool(f1.metrics)
        + 0.2 * min(len(f1.entities), 2)
        + 0.2 * bool(f1.dates)
        + 0.3 * (f1.kind == FactKind.STATUS),
        6,
    )
    assert f1.salience == pytest.approx(expected_f1)
    assert f1.salience > f2.salience
    assert f2.salience == pytest.approx(1.0)

    overridden = ingest(
        notes=notes,
        nlp=nlp_ner,
        fact_overrides={"f002": FactKind.STATUS},
    )
    assert overridden.facts[1].kind == FactKind.STATUS
    assert overridden.facts[1].classification_source == "override"
    assert overridden.facts[1].salience == pytest.approx(1.3)
    assert overridden.digest != base.digest


def test_networkx_graph_nodes_mentions_and_follows_edges(nlp_ner: object) -> None:
    model = ingest([FIXTURES / "status_notes.md"], nlp=nlp_ner)
    graph = model.graph
    assert isinstance(graph, nx.DiGraph)

    # All fact nodes exist with expected metadata
    for fact in model.facts:
        assert graph.has_node(fact.id)
        data = graph.nodes[fact.id]
        assert data["type"] == "fact"
        assert data["kind"] == str(fact.kind)
        assert data["order"] == fact.order

    # Sequential follows edges across reading order
    for prev_fact, curr_fact in zip(model.facts, model.facts[1:], strict=False):
        assert graph.has_edge(prev_fact.id, curr_fact.id)
        assert graph.edges[prev_fact.id, curr_fact.id]["relation"] == "follows"

    # Mentions edges for owner, metric, and date nodes
    owner_node = "owner:Priya Nair"
    assert graph.has_node(owner_node)
    assert graph.nodes[owner_node]["type"] == "owner"
    assert graph.edges["f002", owner_node]["relation"] == "mentions"

    metric_node = "metric:$18,400"
    assert graph.has_node(metric_node)
    assert graph.nodes[metric_node]["type"] == "metric"
    assert graph.edges["f009", metric_node]["relation"] == "mentions"

    date_node = "date:2026-11-24"
    assert graph.has_node(date_node)
    assert graph.nodes[date_node]["type"] == "date"
    assert graph.edges["f005", date_node]["relation"] == "mentions"


def test_ingest_skips_code_and_heading_only_raises_input_error(nlp_ner: object) -> None:
    notes = "# Just a Title\n\n## Just a Heading\n\n```python\nx = 1\n```\n"
    with pytest.raises(InputError, match="No facts could be extracted"):
        ingest(notes=notes, nlp=nlp_ner)


def test_ingest_determinism(nlp_ner: object) -> None:
    m1 = ingest([FIXTURES / "status_notes.md"], notes="Extra inline note.", nlp=nlp_ner)
    m2 = ingest([FIXTURES / "status_notes.md"], notes="Extra inline note.", nlp=nlp_ner)
    assert m1.digest == m2.digest
    assert m1.to_dict() == m2.to_dict()


def test_ingest_edge_cases_and_html_nested_yaml(tmp_path: Path, nlp_ner: object) -> None:
    # Nested YAML key matching + HTML SUMMARY heading & paragraph
    nested_yaml = tmp_path / "nested.yaml"
    nested_yaml.write_text(
        "release:\n  status: TLS migration\n  owner: Priya Nair owns the cluster.\n",
        encoding="utf-8",
    )
    html_file = tmp_path / "notes.html"
    html_file.write_text(
        "<html><body><main>"
        "<h2>Summary</h2><p>Acme Corp launched in Seattle.</p>"
        "<p>First sentence. [risk] Second tagged sentence.</p>"
        "</main></body></html>",
        encoding="utf-8",
    )
    model = ingest([nested_yaml, html_file], nlp=nlp_ner)
    texts = [f.text for f in model.facts]
    assert "The status is TLS migration." in texts
    assert "Priya Nair owns the cluster." in texts
    assert any(f.kind == FactKind.RISK and f.classification_source == "inline_tag" for f in model.facts)
    # Entity node in NetworkX graph
    assert any(
        data.get("type") == "entity"
        for _, data in model.graph.nodes(data=True)
    )

    # Inline tag over Key: value and multi-sentence inline tag
    tagged = ingest(
        notes=(
            "[ask] Risk: vendor delay\n\n"
            "[progress] Built module one. [decision] Kept legacy API.\n\n"
            "Status: iOS rollout\n"
        ),
        nlp=nlp_ner,
    )
    assert tagged.facts[0].kind == FactKind.ASK
    assert tagged.facts[0].classification_source == "inline_tag"
    assert tagged.facts[1].kind == FactKind.PROGRESS
    assert tagged.facts[2].kind == FactKind.DECISION
    assert tagged.facts[3].text == "The status is iOS rollout."

    # Empty directory raises InputError
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(InputError, match="Nothing to write from"):
        ingest([empty_dir], nlp=nlp_ner)

    # Invalid FactKind value in fact_overrides raises InputError
    with pytest.raises(InputError, match="Unknown FactKind"):
        ingest(
            notes="Status: on track.",
            nlp=nlp_ner,
            fact_overrides={"f001": "not_a_kind"},  # type: ignore[dict-item]
        )
