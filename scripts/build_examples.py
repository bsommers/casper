#!/usr/bin/env python3
"""Deterministic generator and drift checker for `examples/outputs/*` (TC-048)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from casper.commands import write_draft
from casper.models import Brief

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = ROOT / "examples" / "edge-migration-status.md"
OUTPUT_DIR = ROOT / "examples" / "outputs"
AUTHORS_DIR = ROOT / "authors"

EXAMPLE_SPECS: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "status-slack.txt",
        {
            "structure": "status_update",
            "modality": "slack",
            "source": "developer",
            "target": "management",
            "author": "bill",
            "seed": 1,
        },
    ),
    (
        "status-email.md",
        {
            "structure": "status_update",
            "modality": "email",
            "source": "developer",
            "target": "management",
            "author": "bill",
            "seed": 1,
        },
    ),
    (
        "decision-memo.md",
        {
            "structure": "decision_memo",
            "modality": "memo",
            "source": "tech_lead",
            "target": "executive",
            "author": "bill",
            "seed": 1,
        },
    ),
    (
        "technical-article.html",
        {
            "structure": "technical_article",
            "modality": "article",
            "source": "developer",
            "target": "engineering",
            "author": "bill",
            "seed": 1,
        },
    ),
    (
        "status-plain.txt",
        {
            "structure": "status_update",
            "modality": "plain",
            "source": "project_manager",
            "target": "management",
            "author": "bill",
            "seed": 1,
        },
    ),
)


def _render_example(spec: dict[str, object]) -> str:
    rel_input = str(EXAMPLE_INPUT.relative_to(ROOT))
    brief = Brief(
        structure=str(spec["structure"]),
        modality=str(spec["modality"]),
        source=str(spec["source"]),
        target=str(spec["target"]),
        author=str(spec["author"]),
        inputs=(rel_input,),
        seed=int(spec["seed"]),  # type: ignore[arg-type]
        authors_dir=str(AUTHORS_DIR),
    )
    result = write_draft(brief)
    if not result.validation.ok:
        raise RuntimeError(
            f"Example {spec['structure']}x{spec['modality']} failed validation: "
            f"{result.validation.findings}"
        )
    text = result.text
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or check Casper worked example outputs.")
    parser.add_argument("--check", action="store_true", help="Fail if examples/outputs/ drifted")
    args = parser.parse_args(argv)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    drifted: list[str] = []

    for filename, spec in EXAMPLE_SPECS:
        expected = _render_example(spec)
        target = OUTPUT_DIR / filename
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != expected:
                drifted.append(filename)
        else:
            target.write_text(expected, encoding="utf-8")

    if args.check:
        if drifted:
            sys.stderr.write(
                f"Example outputs out of sync: {', '.join(drifted)}. "
                "Run: .venv/bin/python scripts/build_examples.py\n"
            )
            return 1
        print(f"OK: {len(EXAMPLE_SPECS)} example outputs match.")
        return 0

    print(f"Generated {len(EXAMPLE_SPECS)} example outputs in examples/outputs/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
