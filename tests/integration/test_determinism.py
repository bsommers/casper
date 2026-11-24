"""TC-037: Byte-level determinism tests within process, across subprocesses, and with author profiles."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from casper import commands, pipeline
from casper.models import Brief

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "status_notes.md"

_SYNTH_CORPUS = """---
title: Deterministic Systems Notes
author: Synth Author
date: 2026-11-10
---

# Deterministic Systems Notes

We build reliable services with small, focused teams. In practice, every release starts with a clear baseline. When you need to ship fast, keep the change tight.

The result is predictable behavior under load. We measure latency first, then we cut unnecessary work. It isn't magic; it's discipline.

Start with the constraint that matters most. Measure the change before expanding scope. You can't fix what you don't observe.

We design clear interfaces for durable systems. Simple contracts beat clever abstractions. When you need to debug an outage, clarity saves hours.

We test every boundary before we ship to production. We don't guess when metrics tell the story. Keep each pull request easy to read, and check the baseline after each rollout.

Repeatable builds prevent silent drift across environments. Clean logs matter during recovery, and small rules keep quality steady across deployments.
"""


def test_tc037_repeated_generate_identical() -> None:
    brief = Brief(
        structure="status_update",
        modality="memo",
        source="developer",
        target="management",
        inputs=(str(FIXTURE),),
        seed=0,
    )
    first = pipeline.generate(brief)
    second = pipeline.generate(brief)

    assert first.validation.ok is True
    assert first.text == second.text
    assert first.fact_trace == second.fact_trace
    assert first.record.record_sha256 == second.record.record_sha256


def test_tc037_cross_process_determinism() -> None:
    brief = Brief(
        structure="decision_memo",
        modality="email",
        source="developer",
        target="management",
        inputs=(str(FIXTURE),),
        seed=0,
    )
    in_proc = pipeline.generate(brief)

    script = (
        "import json; "
        "from casper import pipeline; "
        "from casper.models import Brief; "
        f"b = Brief(structure='decision_memo', modality='email', source='developer', target='management', inputs=({str(FIXTURE)!r},), seed=0); "
        "r = pipeline.generate(b); "
        "print(json.dumps({'text': r.text, 'record_sha256': r.record.record_sha256}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["text"] == in_proc.text
    assert payload["record_sha256"] == in_proc.record.record_sha256


def test_tc037_synthetic_author_seeds_deterministic(tmp_path: Path) -> None:
    corpus_path = tmp_path / "corpus.md"
    corpus_path.write_text(_SYNTH_CORPUS, encoding="utf-8")
    authors_dir = tmp_path / "authors"

    commands.author_build(
        "synth_author",
        "Synth Author",
        [corpus_path],
        authors_dir=authors_dir,
        min_words=100,
    )

    for seed in (0, 7):
        brief = Brief(
            structure="status_update",
            modality="memo",
            source="developer",
            target="management",
            author="synth_author",
            authors_dir=str(authors_dir),
            inputs=(str(FIXTURE),),
            seed=seed,
        )
        first = pipeline.generate(brief)
        second = pipeline.generate(brief)

        assert first.validation.ok is True, first.validation.findings
        assert second.validation.ok is True, second.validation.findings
        assert len(first.record.record_sha256) == 16
        assert first.text == second.text
        assert first.fact_trace == second.fact_trace
        assert first.record.record_sha256 == second.record.record_sha256
