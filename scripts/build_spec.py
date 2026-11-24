#!/usr/bin/env python3
"""Deterministically assemble root SPEC.md from spec/0[0-9]-*.md (ADR 0003)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "spec"
TARGET = ROOT / "SPEC.md"
PART_RE = re.compile(r"^0[0-9]-.*\.md$")


def render_spec(spec_dir: Path = SPEC_DIR) -> str:
    parts = sorted(
        p for p in spec_dir.iterdir() if p.is_file() and PART_RE.match(p.name)
    )
    if not parts:
        raise RuntimeError(f"No spec/0[0-9]-*.md files found in {spec_dir}")

    header = [
        "<!-- DO NOT EDIT DIRECTLY. Generated deterministically by scripts/build_spec.py from spec/0[0-9]-*.md (ADR 0003). -->",
        "",
        "# Casper — Complete Technical Specification",
        "",
        "## Table of Contents",
        "",
    ]
    for p in parts:
        first_line = p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        header.append(f"- `{p.name}` — {first_line}")
    header.append("")

    sections: list[str] = ["\n".join(header)]
    for p in parts:
        body = p.read_text(encoding="utf-8").rstrip("\n")
        sections.append(f"\n---\n\n<!-- source: spec/{p.name} -->\n\n{body}\n")

    return "".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile spec/0[0-9]-*.md into SPEC.md")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify SPEC.md is byte-identical to compiled output without writing.",
    )
    args = parser.parse_args(argv)

    rendered = render_spec(SPEC_DIR)
    if args.check:
        if not TARGET.is_file():
            sys.stderr.write("SPEC.md is missing. Run: python3 scripts/build_spec.py\n")
            return 1
        current = TARGET.read_text(encoding="utf-8")
        if current != rendered:
            sys.stderr.write("SPEC.md is out of date. Run: python3 scripts/build_spec.py\n")
            return 1
        return 0

    TARGET.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
