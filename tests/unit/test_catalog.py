"""TC-015 & TC-032: Author catalog listing, safe profile resolution, and profile diffing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from casper.catalog import AUTHOR_ID_RE, diff_authors, find_profile, list_authors
from casper.errors import ProfileNotFoundError, SecurityError
from casper.features.stability import FEATURE_SPEC_BY_KEY, FEATURE_SPECS, STABILITY_KEYS
from casper.profile import save_profile


def _set_nested(mapping: dict[str, Any], dotted_path: str, value: float) -> None:
    cur = mapping
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _make_profile(
    author_id: str,
    display_name: str,
    *,
    doc_count: int = 2,
    total_words: int = 1200,
    sources_count: int | None = None,
    schema_version: int = 1,
    feature_overrides: dict[str, float] | None = None,
    stdev_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "schema_version": schema_version,
        "author": {"id": author_id, "display_name": display_name, "aliases": []},
        "corpus": {
            "document_count": doc_count,
            "total_words": total_words,
            "avg_doc_words": float(total_words) / max(doc_count, 1),
        },
        "stability": {},
    }
    if sources_count is not None:
        profile["sources"] = [
            {"title": f"Doc {i}", "source": f"doc_{i}.md", "prose_words": 400, "sha256": f"{i:064x}"}
            for i in range(sources_count)
        ]

    f_ov = feature_overrides or {}
    s_ov = stdev_overrides or {}
    for spec in FEATURE_SPECS:
        val = f_ov.get(spec.key, 1.0)
        _set_nested(profile, spec.profile_path, val)
        profile["stability"][spec.key] = {
            "min": val,
            "max": val,
            "stdev": s_ov.get(spec.key, 0.0),
        }
    return profile


def test_list_authors_missing_and_empty_dir(tmp_path: Path) -> None:
    assert list_authors(tmp_path / "does_not_exist") == []

    empty_dir = tmp_path / "authors"
    empty_dir.mkdir()
    assert list_authors(empty_dir) == []

    # Non-primary files only should still yield empty list.
    (empty_dir / "ghost.curated.yaml").write_text("notes: curated\n", encoding="utf-8")
    (empty_dir / "ghost.local.yaml").write_text("author:\n  email: a@b.c\n", encoding="utf-8")
    (empty_dir / "ghost.yaml.bak").write_text("schema_version: 1\n", encoding="utf-8")
    (empty_dir / "ghost.yaml.tmp.1234").write_text("schema_version: 1\n", encoding="utf-8")
    (empty_dir / ".hidden.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (empty_dir / "subdir.yaml").mkdir()
    assert list_authors(empty_dir) == []


def test_list_authors_sorted_and_companions(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    authors_dir.mkdir()

    save_profile(
        authors_dir / "zoe.yaml",
        _make_profile("zoe", "Zoe Z", doc_count=3, total_words=2400, sources_count=0),
    )
    save_profile(
        authors_dir / "alice.yaml",
        _make_profile("alice", "Alice A", doc_count=2, total_words=1500, sources_count=4),
    )
    save_profile(
        authors_dir / "bob.yaml",
        _make_profile("bob", "Bob B", doc_count=5, total_words=3100, schema_version=1),
    )

    (authors_dir / "alice.curated.yaml").write_text("pins: {}\n", encoding="utf-8")
    (authors_dir / "alice.local.yaml").write_text("author:\n  email: a@x.io\n", encoding="utf-8")
    (authors_dir / "bob.curated.yaml").write_text("pins: {}\n", encoding="utf-8")
    (authors_dir / "bob.yaml.bak").write_text("backup: true\n", encoding="utf-8")
    (authors_dir / "bob.tmp.99.yaml").write_text("tmp: true\n", encoding="utf-8")

    summaries = list_authors(authors_dir)
    assert [s.id for s in summaries] == ["alice", "bob", "zoe"]

    alice, bob, zoe = summaries
    assert alice.display_name == "Alice A"
    assert alice.source_count == 4  # uses len(sources)
    assert alice.total_words == 1500
    assert alice.has_curated is True
    assert alice.has_local is True
    assert alice.schema_version == 1

    assert bob.source_count == 5  # falls back to corpus.document_count
    assert bob.has_curated is True
    assert bob.has_local is False

    assert zoe.source_count == 3  # empty sources list falls back to corpus.document_count
    assert zoe.has_curated is False
    assert zoe.has_local is False

    as_dict = alice.to_dict()
    assert as_dict["id"] == "alice"
    assert as_dict["has_curated"] is True


@pytest.mark.parametrize(
    "bad_ref",
    [
        "../etc/passwd",
        "/etc/passwd",
        "foo/bar",
        "foo\\bar",
        "foo.yaml",
        "",
        "   ",
        "-leading-dash",
        "_leading_under",
        "UpperCase",
        "bill\n",
        "bill\x00",
        "a" * 65,
    ],
)
def test_find_profile_strict_rejects_invalid_and_traversal(tmp_path: Path, bad_ref: str) -> None:
    authors_dir = tmp_path / "authors"
    authors_dir.mkdir()
    with pytest.raises(SecurityError):
        find_profile(bad_ref, authors_dir, allow_path=False)


def test_find_profile_strict_rejects_symlink_escape(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    authors_dir.mkdir()
    outside = tmp_path / "secret.yaml"
    save_profile(outside, _make_profile("secret", "Secret"))
    link = authors_dir / "escape.yaml"
    link.symlink_to(outside)

    with pytest.raises(SecurityError):
        find_profile("escape", authors_dir, allow_path=False)
    with pytest.raises(SecurityError):
        find_profile("escape", authors_dir, allow_path=True)


def test_find_profile_strict_existing_and_missing(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    authors_dir.mkdir()
    bill_path = save_profile(authors_dir / "bill_01-a.yaml", _make_profile("bill_01-a", "Bill"))

    assert AUTHOR_ID_RE.fullmatch("bill_01-a") is not None
    assert find_profile("bill_01-a", authors_dir, allow_path=False) == bill_path.resolve()

    with pytest.raises(ProfileNotFoundError):
        find_profile("nobody", authors_dir, allow_path=False)


def test_find_profile_allow_path_true(tmp_path: Path) -> None:
    authors_dir = tmp_path / "authors"
    authors_dir.mkdir()
    catalog_path = save_profile(authors_dir / "bill.yaml", _make_profile("bill", "Bill"))
    direct_path = save_profile(tmp_path / "custom.yaml", _make_profile("custom", "Custom"))
    upper_path = save_profile(authors_dir / "Alice.yaml", _make_profile("Alice", "Alice"))

    assert find_profile("bill", authors_dir, allow_path=True) == catalog_path.resolve()
    assert find_profile(str(direct_path), authors_dir, allow_path=True) == direct_path
    assert find_profile("Alice", authors_dir, allow_path=True) == upper_path.resolve()

    with pytest.raises(ProfileNotFoundError):
        find_profile("missing_id", authors_dir, allow_path=True)
    with pytest.raises(ProfileNotFoundError):
        find_profile(str(tmp_path / "nope.yaml"), authors_dir, allow_path=True)
    with pytest.raises(ProfileNotFoundError):
        find_profile("   ", authors_dir, allow_path=True)
    with pytest.raises(SecurityError):
        find_profile("..", authors_dir, allow_path=True)
    with pytest.raises(SecurityError):
        find_profile("bad\x00id", authors_dir, allow_path=True)


def test_diff_authors_identical_profiles() -> None:
    prof_a = _make_profile("bill", "Bill")
    prof_b = _make_profile("bill", "Bill")

    diff = diff_authors(prof_a, prof_b)
    assert diff.author_a == "bill"
    assert diff.author_b == "bill"
    assert len(diff.feature_deltas) == len(STABILITY_KEYS) == 32
    assert all(entry["delta"] == 0.0 for entry in diff.feature_deltas)
    assert all(entry["normalized_delta"] == 0.0 for entry in diff.feature_deltas)
    # Deterministic tie-break by feature name ascending when all normalized_deltas == 0.
    assert [entry["feature"] for entry in diff.feature_deltas] == sorted(STABILITY_KEYS)


def test_diff_authors_normalized_delta_formula_and_sort() -> None:
    prof_a = _make_profile(
        "alice",
        "Alice",
        feature_overrides={
            # Floor-dominated: floor=2.0, mean_stdev=0.5, 0.1*max=1.5 -> scale=2.0, delta=6.0 -> norm=3.0
            "mean_sentence_length": 9.0,
            # Stdev-dominated: floor=1.2, mean_stdev=4.0, 0.1*max=1.2 -> scale=4.0, delta=-4.0 -> norm=-1.0
            "flesch_kincaid_grade": 12.0,
            # Value-ratio-dominated: floor=8.0, mean_stdev=2.0, 0.1*max=12.0 -> scale=12.0, delta=-24.0 -> norm=-2.0
            "commas_per_1k": 120.0,
            # Largest magnitude: floor=0.01, mean_stdev=0.0, 0.1*max=0.05 -> scale=0.05, delta=0.4 -> norm=8.0
            "exclamation_rate": 0.1,
        },
        stdev_overrides={
            "mean_sentence_length": 0.4,
            "flesch_kincaid_grade": 3.0,
            "commas_per_1k": 2.0,
            "exclamation_rate": 0.0,
        },
    )
    prof_b = _make_profile(
        "bob",
        "Bob",
        feature_overrides={
            "mean_sentence_length": 15.0,
            "flesch_kincaid_grade": 8.0,
            "commas_per_1k": 96.0,
            "exclamation_rate": 0.5,
        },
        stdev_overrides={
            "mean_sentence_length": 0.6,
            "flesch_kincaid_grade": 5.0,
            "commas_per_1k": 2.0,
            "exclamation_rate": 0.0,
        },
    )

    diff = diff_authors(prof_a, prof_b)
    assert diff.author_a == "alice"
    assert diff.author_b == "bob"
    assert len(diff.feature_deltas) == 32

    by_key = {item["feature"]: item for item in diff.feature_deltas}
    assert set(by_key.keys()) == set(STABILITY_KEYS)

    # Verify exact values for each scaling regime.
    assert by_key["mean_sentence_length"]["dimension"] == FEATURE_SPEC_BY_KEY["mean_sentence_length"].dimension
    assert by_key["mean_sentence_length"]["delta"] == pytest.approx(6.0)
    assert by_key["mean_sentence_length"]["normalized_delta"] == pytest.approx(3.0)

    assert by_key["flesch_kincaid_grade"]["delta"] == pytest.approx(-4.0)
    assert by_key["flesch_kincaid_grade"]["normalized_delta"] == pytest.approx(-1.0)

    assert by_key["commas_per_1k"]["delta"] == pytest.approx(-24.0)
    assert by_key["commas_per_1k"]["normalized_delta"] == pytest.approx(-2.0)

    assert by_key["exclamation_rate"]["delta"] == pytest.approx(0.4)
    assert by_key["exclamation_rate"]["normalized_delta"] == pytest.approx(8.0)

    # Top 4 must be ordered descending by |normalized_delta|.
    top_four = [item["feature"] for item in diff.feature_deltas[:4]]
    assert top_four == [
        "exclamation_rate",
        "mean_sentence_length",
        "commas_per_1k",
        "flesch_kincaid_grade",
    ]
    abs_deltas = [abs(item["normalized_delta"]) for item in diff.feature_deltas]
    assert abs_deltas == sorted(abs_deltas, reverse=True)

    # Verify fallback IDs and empty/missing stability maps do not crash.
    minimal_diff = diff_authors({}, {})
    assert minimal_diff.author_a == "author_a"
    assert minimal_diff.author_b == "author_b"
    assert len(minimal_diff.feature_deltas) == 32
    assert minimal_diff.to_dict()["author_a"] == "author_a"
