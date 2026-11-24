"""TC-001: Smoke tests for CLI boot, --help output, and documented subcommands/flags."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from casper import cli

ROOT = Path(__file__).resolve().parents[2]


def _run_cli_help(capsys: pytest.CaptureFixture[str], argv: list[str]) -> str:
    rc = cli.main(argv)
    captured = capsys.readouterr()
    assert rc == 0, f"Expected exit code 0 for {argv!r}, got {rc}; stderr={captured.err!r}"
    return captured.out


def test_tc001_root_help_in_process_and_subprocess(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run_cli_help(capsys, ["--help"])
    for subcmd in ("write", "author", "serve"):
        assert subcmd in out

    proc = subprocess.run(
        [sys.executable, "-m", "casper.cli", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    for subcmd in ("write", "author", "serve"):
        assert subcmd in proc.stdout


def test_tc001_write_help_flags(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run_cli_help(capsys, ["write", "--help"])
    for flag in (
        "--structure",
        "--modality",
        "--source",
        "--target",
        "--author",
        "--fact-override",
        "--authors-dir",
        "--backend",
        "--no-fallback",
        "--brief",
        "--out",
        "--dry-run",
        "--list-options",
        "--backend-status",
        "--json",
    ):
        assert flag in out, f"Missing flag {flag} in `casper write --help`"


def test_tc001_author_help_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run_cli_help(capsys, ["author", "--help"])
    for token in ("build", "inspect", "show", "score", "list", "diff", "--authors-dir"):
        assert token in out, f"Missing {token!r} in `casper author --help`"


def test_tc001_serve_help_flags(capsys: pytest.CaptureFixture[str]) -> None:
    out = _run_cli_help(capsys, ["serve", "--help"])
    for flag in ("--host", "--port", "--authors-dir"):
        assert flag in out, f"Missing flag {flag} in `casper serve --help`"
