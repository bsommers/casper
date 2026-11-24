"""System tests verifying worked example inputs, outputs, and CLI reproduction (TC-048)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from casper import cli

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_OUTPUT_FILES = (
    "status-slack.txt",
    "status-email.md",
    "decision-memo.md",
    "technical-article.html",
    "status-plain.txt",
)


def test_tc048_example_artifacts_exist_and_non_empty() -> None:
    required_paths = [
        ROOT / "examples" / "edge-migration-status.md",
        ROOT / "authors" / "bill.yaml",
        *(ROOT / "examples" / "outputs" / name for name in EXPECTED_OUTPUT_FILES),
    ]
    for path in required_paths:
        assert path.is_file(), f"Missing required example artifact: {path}"
        assert path.stat().st_size > 0, f"Empty example artifact: {path}"


def test_tc048_build_examples_check_passes() -> None:
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_examples.py"), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr or res.stdout


def test_tc048_cli_reproduces_status_slack_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(ROOT)
    rc = cli.main(
        [
            "write",
            "--author",
            "bill",
            "--source",
            "developer",
            "--target",
            "management",
            "--structure",
            "status_update",
            "--modality",
            "slack",
            "-i",
            "examples/edge-migration-status.md",
            "--seed",
            "1",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    expected = (ROOT / "examples" / "outputs" / "status-slack.txt").read_text(encoding="utf-8")
    assert captured.out == expected
