#!/usr/bin/env python3
"""Leave-one-out voice conformance calibration over a corpus directory."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from casper.conformance import score
from casper.documents import prose_word_count
from casper.errors import InputError
from casper.loaders import collect_input_paths, load_document
from casper.parsing import load_nlp
from casper.profile import build_profile


def calibrate_directory(
    corpus_dir: Path,
    *,
    min_words: int = 150,
    author_id: str = "calibration",
    author_name: str = "Calibration Author",
    nlp: Any | None = None,
) -> list[dict[str, Any]]:
    """Run leave-one-out conformance scoring across all eligible documents in `corpus_dir`."""
    paths = collect_input_paths([corpus_dir])
    eligible: list[tuple[str, Any]] = []
    for raw_path in paths:
        doc = load_document(raw_path)
        if prose_word_count(doc) >= min_words:
            eligible.append((raw_path, doc))

    if len(eligible) < 2:
        raise InputError(
            f"Leave-one-out calibration requires at least 2 eligible documents "
            f"(>= {min_words} prose words); found {len(eligible)} in {corpus_dir}"
        )

    active_nlp = nlp if nlp is not None else load_nlp(ner=False)
    results: list[dict[str, Any]] = []

    for idx, (held_path, held_doc) in enumerate(eligible):
        train_paths = [p for j, (p, _d) in enumerate(eligible) if j != idx]
        profile = build_profile(
            author_id,
            author_name,
            train_paths,
            min_words=min_words,
            nlp=active_nlp,
        )
        report = score(profile, held_doc, nlp=active_nlp)
        top_gap = report.largest_gaps[0].feature if report.largest_gaps else "-"
        results.append(
            {
                "document": Path(held_path).name,
                "source": held_path,
                "words": report.word_count,
                "overall": round(report.overall, 2),
                "band": str(report.band),
                "confidence": str(report.confidence),
                "top_gap": top_gap,
            }
        )

    return results


def _format_table(rows: Sequence[dict[str, Any]]) -> str:
    doc_width = max(len("Document"), *(len(str(r["document"])) for r in rows))
    gap_width = max(len("Top Gap"), *(len(str(r["top_gap"])) for r in rows))

    header = (
        f"{'Document':<{doc_width}}  {'Words':>6}  {'Score':>6}  "
        f"{'Band':<9}  {'Conf':<6}  {'Top Gap':<{gap_width}}"
    )
    sep = "-" * len(header)
    lines = [header, sep]
    for row in rows:
        lines.append(
            f"{row['document']:<{doc_width}}  {row['words']:>6d}  {row['overall']:>6.2f}  "
            f"{row['band']:<9}  {row['confidence']:<6}  {row['top_gap']:<{gap_width}}"
        )

    scores = [float(r["overall"]) for r in rows]
    band_counts = Counter(str(r["band"]) for r in rows)
    band_summary = ", ".join(f"{band}={count}" for band, count in sorted(band_counts.items()))
    lines.append(sep)
    lines.append(
        f"Docs: {len(rows)} | Mean: {statistics.mean(scores):.2f} | "
        f"Median: {statistics.median(scores):.2f} | Min: {min(scores):.2f} | "
        f"Max: {max(scores):.2f} | Bands: {band_summary}"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run leave-one-out voice conformance calibration over a corpus directory."
    )
    parser.add_argument("corpus_dir", type=Path, help="Directory containing corpus documents")
    parser.add_argument(
        "--min-words",
        type=int,
        default=150,
        help="Minimum prose words per document (default: 150)",
    )
    parser.add_argument("--author-id", default="calibration", help="Temporary profile author ID")
    parser.add_argument(
        "--author-name",
        default="Calibration Author",
        help="Temporary profile display name",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON output",
    )
    args = parser.parse_args(argv)

    try:
        rows = calibrate_directory(
            args.corpus_dir,
            min_words=args.min_words,
            author_id=args.author_id,
            author_name=args.author_name,
        )
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        scores = [float(r["overall"]) for r in rows]
        payload = {
            "corpus_dir": str(args.corpus_dir),
            "count": len(rows),
            "mean": round(statistics.mean(scores), 2),
            "median": round(statistics.median(scores), 2),
            "min": round(min(scores), 2),
            "max": round(max(scores), 2),
            "results": rows,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
