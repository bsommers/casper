"""TC-010: Shipped YAML libraries, project_dir overlay, and combo validation."""

from __future__ import annotations

from pathlib import Path

import yaml

from casper.libraries import check_combo, load_libraries
from casper.models import PersonaKind


def test_load_shipped_libraries_counts_and_digest() -> None:
    libs1 = load_libraries()
    libs2 = load_libraries()
    assert libs1.digest == libs2.digest
    assert len(libs1.digest) == 64

    # 10 personas: 5 source + 5 target including both product_owner roles
    assert len(libs1.personas) == 10
    assert (PersonaKind.SOURCE, "product_owner") in libs1.personas
    assert (PersonaKind.TARGET, "product_owner") in libs1.personas
    assert len([k for k in libs1.personas if k[0] == PersonaKind.SOURCE]) == 5
    assert len([k for k in libs1.personas if k[0] == PersonaKind.TARGET]) == 5

    # 3 structures, 11 valid structure x modality pairs
    assert set(libs1.structures) == {"status_update", "decision_memo", "technical_article"}
    valid_pairs = sum(len(s.compatible_modalities) for s in libs1.structures.values())
    assert valid_pairs == 11

    # 5 modalities
    assert set(libs1.modalities) == {"slack", "email", "memo", "article", "plain"}

    # Glossary & lexicons
    assert "latency" in libs1.glossary.plain
    assert "utilize" in libs1.glossary.preferred
    assert "synergy" in libs1.glossary.banned
    assert len(libs1.lexicons["function_words"]) == 60

    # Valid combo passes
    check_combo(libs1, "status_update", "slack", "management", "developer")


def test_project_dir_overlay_changes_digest_and_overrides(tmp_path: Path) -> None:
    base = load_libraries()
    (tmp_path / "glossaries").mkdir()
    (tmp_path / "glossaries" / "custom.yaml").write_text(
        yaml.safe_dump({"banned": ["buzzword"], "preferred": {"commence": "start"}}),
        encoding="utf-8",
    )
    overlaid = load_libraries(project_dir=tmp_path)
    assert overlaid.digest != base.digest
    assert "buzzword" in overlaid.glossary.banned
    assert overlaid.glossary.preferred["commence"] == "start"
