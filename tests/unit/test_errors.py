"""TC-035: Negative validation and typed error checks (expanded across Tasks 3, 5, 8, 13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from casper import cli, commands, pipeline
from casper.errors import InputError, LibraryError, ProfileError
from casper.facts import ingest
from casper.layers import resolve
from casper.libraries import check_combo, load_libraries
from casper.models import Brief, FactKind


def test_invalid_structure_modality_combo_raises_library_error() -> None:
    libs = load_libraries()
    with pytest.raises(LibraryError) as exc_info:
        check_combo(libs, "status_update", "article", "management", "developer")
    assert "slack" in str(exc_info.value)


def test_unknown_structure_modality_and_personas_raise_library_error() -> None:
    libs = load_libraries()
    with pytest.raises(LibraryError, match="status_update"):
        check_combo(libs, "nonexistent_struct", "slack", "management", "developer")
    with pytest.raises(LibraryError, match="slack"):
        check_combo(libs, "status_update", "nonexistent_mod", "management", "developer")
    with pytest.raises(LibraryError, match="management"):
        check_combo(libs, "status_update", "slack", "nonexistent_target", "developer")
    with pytest.raises(LibraryError, match="developer"):
        check_combo(libs, "status_update", "slack", "management", "nonexistent_source")


def test_empty_fact_ingest_raises_input_error() -> None:
    with pytest.raises(InputError, match="Nothing to write from"):
        ingest()
    with pytest.raises(InputError, match="Nothing to write from"):
        ingest(notes="   \n\t  ")


def test_unknown_fact_override_id_raises_input_error() -> None:
    with pytest.raises(InputError, match="Unknown fact id in fact_overrides: f999"):
        ingest(
            notes="Status: on track.",
            fact_overrides={"f999": FactKind.RISK},
        )


def test_layer_plain_list_overwrite_raises_profile_error() -> None:
    """TC-035: plain list assignment in curated/local/overlay raises ProfileError."""
    generated = {
        "author": {"id": "bill", "aliases": ["William"]},
        "style_guide": [{"id": "sentences", "area": "sentences", "rule": "Keep concise."}],
    }
    with pytest.raises(ProfileError, match=r"\$add"):
        resolve(generated, curated={"author": {"aliases": ["Will"]}})

    with pytest.raises(ProfileError, match=r"\$add"):
        resolve(generated, local={"custom": {"tags": ["new"]}})

    with pytest.raises(ProfileError, match=r"\$add"):
        resolve(
            generated,
            curated={"overlays": {"slack": {"author": {"aliases": ["BillS"]}}}},
            overlays=("slack",),
        )

    with pytest.raises(ProfileError, match="style_guide"):
        resolve(generated, curated={"style_guide": [{"id": "x", "area": "x", "rule": "y"}]})

    with pytest.raises(ProfileError, match="Unknown list directive"):
        resolve(generated, curated={"author": {"aliases": {"$append": ["Will"]}}})

    with pytest.raises(ProfileError, match="must be a list"):
        resolve(generated, curated={"author": {"aliases": {"$add": "Will"}}})


def test_unknown_backend_raises_input_error_and_cli_exits_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief = Brief(
        structure="status_update",
        modality="slack",
        source="developer",
        target="management",
        notes="Status: Migration is on track.",
        backend="foobar",
    )
    with pytest.raises(InputError, match="Unknown backend"):
        pipeline.generate(brief)

    rc = cli.main(
        [
            "write",
            "--structure",
            "status_update",
            "--modality",
            "slack",
            "--source",
            "developer",
            "--target",
            "management",
            "--notes",
            "Status: Migration is on track.",
            "--backend",
            "foobar",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "input-error" in captured.err


def test_score_draft_raw_with_overlay_raises_input_error_and_cli_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft_path = tmp_path / "draft.md"
    draft_path.write_text("Status: Rollout is on track.\n", encoding="utf-8")
    authors_dir = tmp_path / "authors"

    with pytest.raises(InputError, match="Cannot combine --raw with --overlay"):
        commands.score_draft(
            "alice",
            draft_path,
            authors_dir=authors_dir,
            raw=True,
            overlay="slack",
        )

    rc = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "score",
            "alice",
            str(draft_path),
            "--raw",
            "--overlay",
            "slack",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "input-error" in captured.err


@pytest.mark.parametrize(
    "bad_override",
    ["f001", "=risk", "f001=unknown_kind"],
)
def test_invalid_fact_override_cli_exits_2(
    bad_override: str, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(
        [
            "write",
            "--notes",
            "Status: Rollout is on track.",
            "--dry-run",
            "--fact-override",
            bad_override,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "input-error" in captured.err
