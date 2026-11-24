"""TC-047: Performance latency budget tests for pipeline.generate and conformance.score."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from casper import conformance, pipeline
from casper.features import analyze
from casper.models import Block, BlockKind, Brief, Document
from casper.parsing import load_nlp

_FACT_TEMPLATES: tuple[str, ...] = (
    "Status: Cluster node {i} cutover reached {pct}% traffic.",
    "Progress: Completed rollout batch {i} across {n} zones with latency {ms}ms.",
    "Metric: Cache hit rate for shard {i} improved by +{delta}% to 94.{d}%.",
    "Risk: Legacy client pool {i} remains blocked on rotation window {i}.",
    "Next step: Finish validation for batch {i} on 2026-11-28.",
    "Decision: Keep dual-stack fallback active for region {i} through December.",
    "Background: Worker pool {i} replaces legacy proxy nodes to reduce tail latency.",
    "Ask: Approve maintenance window {i} for final traffic drain.",
)


@pytest.fixture(scope="module", autouse=True)
def _warm_spacy_models() -> tuple[Any, Any]:
    return load_nlp(ner=True), load_nlp(ner=False)


def _build_100_fact_markdown(path: Path) -> Path:
    lines = ["# Performance Synthetic Notes", ""]
    for idx in range(1, 101):
        tmpl = _FACT_TEMPLATES[(idx - 1) % len(_FACT_TEMPLATES)]
        lines.append(
            tmpl.format(
                i=idx,
                pct=50 + (idx % 45),
                n=2 + (idx % 10),
                ms=18 + (idx % 30),
                delta=2 + (idx % 8),
                d=idx % 9,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _build_5000_word_doc() -> Document:
    # Each sentence has 10 words; 500 sentences = 5,000 words across 100 paragraphs.
    sentence = "We measure system latency carefully before shipping every release today."
    paragraphs = [" ".join([sentence] * 5) for _ in range(100)]
    blocks: list[Block] = []
    for idx, para in enumerate(paragraphs):
        if idx % 10 == 0:
            blocks.append(Block(kind=BlockKind.HEADING, text=f"Section {idx // 10 + 1}", level=2))
        blocks.append(Block(kind=BlockKind.PARAGRAPH, text=para))
    return Document(source="<perf-5000w>", format="markdown", blocks=tuple(blocks))


def test_tc047_pipeline_generate_100_facts_budget(tmp_path: Path) -> None:
    input_path = _build_100_fact_markdown(tmp_path / "facts_100.md")
    brief = Brief(
        structure="status_update",
        modality="memo",
        source="developer",
        target="management",
        inputs=(str(input_path),),
        seed=0,
    )

    start = time.perf_counter()
    result = pipeline.generate(brief)
    elapsed = time.perf_counter() - start

    assert len(result.facts) >= 100
    assert result.validation.ok is True, result.validation.findings
    assert elapsed < 2.0, f"pipeline.generate on 100 facts took {elapsed:.3f}s (budget < 2.0s)"


def test_tc047_conformance_score_5000_words_budget() -> None:
    nlp_no_ner = load_nlp(ner=False)
    sample_doc = Document(
        source="<perf-profile>",
        format="markdown",
        blocks=(
            Block(kind=BlockKind.HEADING, text="Baseline checks", level=2),
            Block(
                kind=BlockKind.PARAGRAPH,
                text=(
                    "We measure system latency carefully before shipping every release today. "
                    "We measure system latency carefully before shipping every release today. "
                    "We measure system latency carefully before shipping every release today."
                ),
            ),
        ),
    )
    feats = analyze([sample_doc], nlp=nlp_no_ner)
    profile: dict[str, Any] = {
        "schema_version": 1,
        "author": {"id": "perf_author", "display_name": "Perf Author", "aliases": []},
        "corpus": {
            "document_count": 1,
            "total_words": int(feats["lexical"]["words"]),
            "avg_doc_words": float(feats["lexical"]["words"]),
        },
        **feats,
    }
    doc_5k = _build_5000_word_doc()

    start = time.perf_counter()
    report = conformance.score(profile, doc_5k)
    elapsed = time.perf_counter() - start

    assert report.word_count >= 5000
    assert elapsed < 1.0, f"conformance.score on 5000 words took {elapsed:.3f}s (budget < 1.0s)"
