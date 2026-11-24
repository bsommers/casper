#!/usr/bin/env python3
"""Deterministic 9-mode fake CLI agent (`claude` / `agy`) for offline tests (TC-041, TC-042)."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
_FACT_LINE_RE = re.compile(r"^-\s+\[(f\d{3,})\]\s+\([^)]+\)\s+(.+?)\s*$")


def _parse_prompt_sections(prompt: str) -> list[tuple[str, list[tuple[str, str]]]]:
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    current_name: str | None = None
    current_facts: list[tuple[str, str]] = []

    for line in prompt.splitlines():
        sec_m = _SECTION_RE.match(line.strip())
        if sec_m:
            if current_name is not None:
                sections.append((current_name, current_facts))
            current_name = sec_m.group(1).strip()
            current_facts = []
            continue
        fact_m = _FACT_LINE_RE.match(line.strip())
        if fact_m and current_name is not None:
            current_facts.append((fact_m.group(1), fact_m.group(2)))

    if current_name is not None:
        sections.append((current_name, current_facts))
    return sections


def _reword_safely(text: str) -> str:
    """Apply benign lexical rewording (no new numbers, no new proper names, same polarity)."""
    # Add benign lowercase adjectives/adverbs that preserve polarity and avoid proper nouns.
    stripped = text.rstrip(".!?")
    return f"Currently, {stripped[0].lower() + stripped[1:] if stripped and stripped[0].isupper() and not stripped.split()[0].isupper() and stripped.split()[0] not in {'I', 'API', 'SQL', 'SLA', 'SLO'} else stripped} as verified."


def _flip_polarity(text: str) -> str:
    """Deliberately invert polarity of a grounded sentence."""
    replacements = (
        ("on track", "blocked"),
        ("approved", "rejected"),
        ("passed", "failed"),
        ("enabled", "disabled"),
        ("completed", "not completed"),
        (" is ", " is not "),
        (" are ", " are not "),
        (" will ", " will not "),
    )
    for src, dst in replacements:
        if src in text.lower():
            return re.sub(re.escape(src), dst, text, count=1, flags=re.IGNORECASE)
    return f"It is not true that {text[0].lower() + text[1:] if text else text}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    mode = os.environ.get("CASPER_FAKE_MODE", "good").strip().lower()
    sleep_s = float(os.environ.get("CASPER_FAKE_SLEEP", "5.0"))
    version_str = os.environ.get("CASPER_FAKE_VERSION", "fake-agent 1.0.0")

    if "--version" in args:
        if mode == "hang":
            time.sleep(sleep_s)
        if mode == "fail":
            sys.stderr.write("fake-agent version check failed\n")
            return 1
        sys.stdout.write(f"{version_str}\n")
        return 0

    # Parse `-p --output-format text [--model MODEL] <prompt>`
    prompt = ""
    i = 0
    positionals: list[str] = []
    while i < len(args):
        tok = args[i]
        if tok in {"--output-format", "--model"}:
            i += 2
            continue
        if tok in {"-p", "--print"}:
            i += 1
            continue
        positionals.append(tok)
        i += 1
    if positionals:
        prompt = positionals[-1]

    dump_path = os.environ.get("CASPER_FAKE_DUMP_PROMPT", "").strip()
    if dump_path:
        Path(dump_path).write_text(prompt, encoding="utf-8")

    if mode == "hang":
        time.sleep(sleep_s)
        return 0

    if mode == "fail":
        sys.stderr.write("simulated CLI backend authentication failure\n")
        return 1

    if mode == "empty":
        sys.stdout.write("   \n")
        return 0

    sections = _parse_prompt_sections(prompt)
    if not sections:
        sys.stderr.write("no sections found in prompt\n")
        return 1

    out_lines: list[str] = []
    first_done = False
    for sec_name, facts in sections:
        out_lines.append(f"## {sec_name}")
        for fid, text in facts:
            if mode == "good":
                out_lines.append(f"{text} [{fid}]")
            elif mode == "invent":
                if not first_done:
                    out_lines.append(f"{text.rstrip('.')} saving $999,999 immediately. [{fid}]")
                    first_done = True
                else:
                    out_lines.append(f"{text} [{fid}]")
            elif mode == "rename":
                if not first_done:
                    out_lines.append(f"ZorgCorp confirmed that {text.rstrip('.')} [{fid}]")
                    first_done = True
                else:
                    out_lines.append(f"{text} [{fid}]")
            elif mode == "polarity":
                if not first_done:
                    out_lines.append(f"{_flip_polarity(text)} [{fid}]")
                    first_done = True
                else:
                    out_lines.append(f"{text} [{fid}]")
            elif mode == "uncited":
                if not first_done:
                    out_lines.append(text)
                    first_done = True
                else:
                    out_lines.append(f"{text} [{fid}]")
            elif mode == "reword":
                out_lines.append(f"{_reword_safely(text)} [{fid}]")
            else:
                sys.stderr.write(f"unknown CASPER_FAKE_MODE: {mode}\n")
                return 2
        out_lines.append("")

    sys.stdout.write("\n".join(out_lines).strip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
