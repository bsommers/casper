"""TC-002: Verify SPEC.md is deterministically synced with spec/0[0-9]-*.md."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_spec_check_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_spec.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"SPEC.md drift detected:\n{proc.stderr}"
    spec_text = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    assert "00-overview.md" in spec_text
    assert "05-brand-assets.md" in spec_text
