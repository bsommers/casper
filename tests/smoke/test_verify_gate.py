"""TC-049: Verify scripts/verify.sh CLI contract without infinite recursion."""

from __future__ import annotations

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts" / "verify.sh"


def test_verify_list_stages() -> None:
    proc = subprocess.run(
        ["bash", str(VERIFY), "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    stages = proc.stdout.strip().splitlines()
    for required in ("lint-ruff", "type-mypy", "spec-sync", "secret-scan", "smoke", "unit", "coverage"):
        assert required in stages


def test_verify_isolated_execution(tmp_path: Path) -> None:
    if os.environ.get("CASPER_IN_VERIFY") == "1":
        # Guard against recursive full-suite execution; still exercise lightweight --only spec-sync into isolated dir.
        out_dir = tmp_path / "verify_out"
        env = dict(os.environ)
        env["CASPER_VERIFY_DIR"] = str(out_dir)
        proc = subprocess.run(
            ["bash", str(VERIFY), "--only", "spec-sync"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        out_dir = tmp_path / "verify_out"
        env = dict(os.environ)
        env["CASPER_VERIFY_DIR"] = str(out_dir)
        proc = subprocess.run(
            ["bash", str(VERIFY), "--only", "spec-sync", "secret-scan"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    assert proc.returncode == 0, f"verify.sh failed: {proc.stdout} {proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"Expected exactly 1 stdout line, got: {lines!r}"
    assert re.match(r"^PASS \d+/\d+ \d+s skips=\d+$", lines[0]), f"Bad summary line: {lines[0]}"

    assert (out_dir / "STATUS").is_file()
    assert (out_dir / "summary.tsv").is_file()
    assert (out_dir / "report.md").is_file()
    assert (out_dir / "junit.xml").is_file()
    ET.parse(out_dir / "junit.xml")

    status_proc = subprocess.run(
        ["bash", str(VERIFY), "--status"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status_proc.returncode == 0
    assert status_proc.stdout.strip() == lines[0]
