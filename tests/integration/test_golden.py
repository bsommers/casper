"""TC-016: Golden-output integration tests across all 11 structure x modality pairs."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from casper import pipeline
from casper.libraries import load_libraries
from casper.models import Brief

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "status_notes.md"
GOLDEN_DIR = ROOT / "tests" / "golden"

GOLDEN_PAIRS: tuple[tuple[str, str], ...] = (
    ("status_update", "slack"),
    ("status_update", "email"),
    ("status_update", "memo"),
    ("status_update", "plain"),
    ("decision_memo", "memo"),
    ("decision_memo", "email"),
    ("decision_memo", "article"),
    ("decision_memo", "plain"),
    ("technical_article", "article"),
    ("technical_article", "memo"),
    ("technical_article", "plain"),
)


def test_tc016_golden_covers_all_valid_combos() -> None:
    libs = load_libraries()
    expected = {
        (sid, mid)
        for sid, struct in libs.structures.items()
        for mid in struct.compatible_modalities
    }
    assert len(expected) == 11
    assert set(GOLDEN_PAIRS) == expected


@pytest.mark.parametrize(("structure", "modality"), GOLDEN_PAIRS)
def test_tc016_golden_matrix(structure: str, modality: str) -> None:
    brief = Brief(
        structure=structure,
        modality=modality,
        source="developer",
        target="management",
        inputs=(str(FIXTURE),),
        seed=0,
    )
    result = pipeline.generate(brief)

    assert result.validation.ok is True, f"Validation failed: {result.validation.findings}"
    assert len(result.fact_trace) > 0
    assert len(result.record.record_sha256) == 16

    golden_path = GOLDEN_DIR / f"{structure}__{modality}.txt"
    rendered_bytes = result.text.encode("utf-8")

    if os.environ.get("CASPER_UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_bytes(rendered_bytes)
        return

    assert golden_path.is_file(), (
        f"Missing golden file {golden_path}; run with CASPER_UPDATE_GOLDEN=1 to generate."
    )
    assert rendered_bytes == golden_path.read_bytes()
