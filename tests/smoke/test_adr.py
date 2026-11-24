"""TC-003: Verify ADR register parity and accepted ADR enforcement links."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "docs" / "adr"


def test_adr_register_parity_and_enforcement() -> None:
    readme = ADR_DIR / "README.md"
    assert readme.is_file(), "docs/adr/README.md missing"
    assert (ADR_DIR / "TEMPLATE.md").is_file(), "docs/adr/TEMPLATE.md missing"

    adr_files = sorted(
        p for p in ADR_DIR.iterdir() if p.is_file() and re.match(r"^\d{4}-.*\.md$", p.name)
    )
    assert len(adr_files) >= 12, f"Expected >=12 ADRs, found {len(adr_files)}"

    readme_text = readme.read_text(encoding="utf-8")
    linked = set(re.findall(r"\((\d{4}-[^)]+\.md)\)", readme_text))
    actual = {p.name for p in adr_files}
    assert linked == actual, f"ADR index drift: linked={linked - actual}, unindexed={actual - linked}"

    for adr_file in adr_files:
        text = adr_file.read_text(encoding="utf-8")
        status_match = re.search(r"^\*\*Status:\*\*\s*(\w+)", text, re.MULTILINE)
        assert status_match, f"{adr_file.name} missing **Status:** line"
        status = status_match.group(1).lower()
        if status == "accepted":
            enf_match = re.search(r"^\*\*Enforced by:\*\*\s*(.+)$", text, re.MULTILINE)
            assert enf_match and enf_match.group(1).strip(), (
                f"Accepted ADR {adr_file.name} must have non-empty **Enforced by:**"
            )
