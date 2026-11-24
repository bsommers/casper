"""Unit tests for three-layer profile resolution, tamper guard, and drift reporting (TC-008, TC-031, TC-036)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from casper.errors import ProfileError, ProfileNotFoundError, ProfileTamperedError
from casper.layers import drift_report, extract_pins, load_resolved_profile, resolve
from casper.profile import (
    check_profile_writable,
    compute_body_sha256,
    load_profile,
    save_profile,
)


def _sample_generated_profile() -> dict[str, Any]:
    profile: dict[str, Any] = {
        "schema_version": 1,
        "author": {
            "id": "bill",
            "display_name": "Bill",
            "aliases": ["William", "Billy"],
        },
        "generated": {
            "tool": "casper",
            "tool_version": "0.1.0",
            "date": "2026-11-20T00:00:00Z",
            "spacy_model": "en_core_web_sm",
            "corpus_sha256": "a" * 64,
            "body_sha256": "",
        },
        "style_guide": [
            {"id": "sentences", "area": "sentences", "rule": "Generated sentence rule."},
            {"id": "paragraphs", "area": "paragraphs", "rule": "Generated paragraph rule."},
            {"id": "voice", "area": "voice", "rule": "Generated voice rule."},
        ],
        "sentences": {
            "length_words": {"mean": 16.0, "median": 15.0},
            "short_rate_le8": 0.16,
            "passive_rate": 0.08,
        },
        "voice": {
            "contractions_per_1k": 8.0,
        },
        "stability": {
            "mean_sentence_length": {"min": 14.0, "max": 18.0, "stdev": 1.2},
            "contractions_per_1k": {"min": 5.0, "max": 11.0, "stdev": 2.5},
            "passive_rate": {"min": 0.05, "max": 0.11, "stdev": 0.02},
        },
    }
    profile["generated"]["body_sha256"] = compute_body_sha256(profile)
    return profile


def test_tc008_resolve_precedence_lists_style_guide_overlays_and_provenance() -> None:
    """TC-008: exact layer precedence, list ops, style_guide edits, overlay stripping, provenance."""
    generated = _sample_generated_profile()
    curated: dict[str, Any] = {
        "author": {
            "display_name": "Bill C.",
            "aliases": {"$remove": ["Billy"], "$add": ["Will", "William"]},
        },
        "style_guide": {
            "sentences": "Curated sentence rule.",
            "paragraphs": "$remove",
            "custom_tone": {"area": "voice", "rule": "Prefer active verbs."},
        },
        "pins": {
            "mean_sentence_length": {"value": 15.0, "stdev": 1.5},
        },
        "overlays": {
            "slack": {
                "pins": {
                    "mean_sentence_length": {"value": 12.0},
                },
                "author": {
                    "aliases": {"$add": ["BillS"]},
                },
                "style_guide": {
                    "sentences": "Slack curated sentence rule.",
                },
            },
            "email": {
                "pins": {"mean_sentence_length": {"value": 18.0}},
            },
        },
    }
    local: dict[str, Any] = {
        "author": {
            "display_name": "Bill Local",
            "email": "bill@example.invalid",
        },
        "pins": {
            "contractions_per_1k": {"value": 9.0},
        },
        "overlays": {
            "slack": {
                "pins": {
                    "mean_sentence_length": {"value": 11.0},
                },
                "style_guide": {
                    "voice": {"area": "voice", "rule": "Slack local voice rule."},
                },
            },
        },
    }

    gen_snap = copy.deepcopy(generated)
    cur_snap = copy.deepcopy(curated)
    loc_snap = copy.deepcopy(local)

    merged, prov = resolve(generated, curated, local, overlays=("slack",))

    # Inputs are never mutated.
    assert generated == gen_snap
    assert curated == cur_snap
    assert local == loc_snap

    # Overlays container key is stripped from merged output.
    assert "overlays" not in merged
    assert not any(k == "overlays" or k.startswith("overlays.") for k in prov)

    # Scalar precedence: local beats curated beats generated.
    assert merged["author"]["display_name"] == "Bill Local"
    assert prov["author.display_name"] == "local"
    assert merged["author"]["email"] == "bill@example.invalid"
    assert prov["author.email"] == "local"
    assert merged["author"]["id"] == "bill"
    assert prov["author.id"] == "generated"

    # List algebra ($remove, $add dedup, overlay $add).
    assert merged["author"]["aliases"] == ["William", "Will", "BillS"]
    assert prov["author.aliases"] == "curated.overlays.slack"

    # Style guide edits (replace, remove, append, overlay update).
    sg_by_id = {entry["id"]: entry for entry in merged["style_guide"]}
    assert "paragraphs" not in sg_by_id
    assert sg_by_id["sentences"]["rule"] == "Slack curated sentence rule."
    assert sg_by_id["custom_tone"] == {
        "id": "custom_tone",
        "area": "voice",
        "rule": "Prefer active verbs.",
    }
    assert sg_by_id["voice"] == {"id": "voice", "area": "voice", "rule": "Slack local voice rule."}
    assert prov["style_guide.sentences"] == "curated.overlays.slack"
    assert prov["style_guide.paragraphs"] == "curated"
    assert prov["style_guide.custom_tone"] == "curated"
    assert prov["style_guide.voice"] == "local.overlays.slack"

    # Pins precedence: local.overlays.slack > curated.overlays.slack > local > curated.
    assert merged["pins"]["mean_sentence_length"]["value"] == 11.0
    assert merged["pins"]["mean_sentence_length"]["stdev"] == 1.5
    assert merged["pins"]["contractions_per_1k"]["value"] == 9.0
    assert prov["pins.mean_sentence_length.value"] == "local.overlays.slack"
    assert prov["pins.mean_sentence_length.stdev"] == "curated"
    assert prov["pins.contractions_per_1k.value"] == "local"

    # Helper extract_pins returns numeric pins only.
    pins = extract_pins(merged)
    assert pins == {
        "mean_sentence_length": {"value": 11.0, "stdev": 1.5},
        "contractions_per_1k": {"value": 9.0},
    }


def test_resolve_list_replace_and_new_list_creation() -> None:
    generated = _sample_generated_profile()
    curated: dict[str, Any] = {
        "author": {"aliases": {"$replace": ["OnlyAlias"]}},
        "custom": {"tags": {"$add": ["tech", "concise", "tech"]}},
    }
    merged, prov = resolve(generated, curated)
    assert merged["author"]["aliases"] == ["OnlyAlias"]
    assert merged["custom"]["tags"] == ["tech", "concise"]
    assert prov["author.aliases"] == "curated"
    assert prov["custom.tags"] == "curated"


def test_load_resolved_profile_companions_and_errors(tmp_path: Path) -> None:
    generated = _sample_generated_profile()
    profile_path = tmp_path / "bill.yaml"
    save_profile(profile_path, generated)

    # No companions -> resolves generated cleanly.
    merged_only, prov_only = load_resolved_profile(profile_path)
    assert merged_only["author"]["display_name"] == "Bill"
    assert prov_only["author.display_name"] == "generated"

    # Add curated and empty local companion.
    (tmp_path / "bill.curated.yaml").write_text(
        yaml.safe_dump(
            {
                "author": {"display_name": "Bill Curated"},
                "overlays": {"memo": {"pins": {"mean_sentence_length": {"value": 17.0}}}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "bill.local.yaml").write_text("# comment only\n", encoding="utf-8")

    merged, prov = load_resolved_profile(profile_path, overlays=("memo",))
    assert merged["author"]["display_name"] == "Bill Curated"
    assert merged["pins"]["mean_sentence_length"]["value"] == 17.0
    assert prov["pins.mean_sentence_length.value"] == "curated.overlays.memo"
    assert "overlays" not in merged

    # Corrupt companion YAML raises ProfileError.
    (tmp_path / "bill.curated.yaml").write_text(":::bad: [yaml", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_resolved_profile(profile_path)

    # Non-mapping companion YAML raises ProfileError.
    (tmp_path / "bill.curated.yaml").write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_resolved_profile(profile_path)

    # Missing base profile raises ProfileNotFoundError.
    with pytest.raises(ProfileNotFoundError):
        load_resolved_profile(tmp_path / "missing.yaml")


def test_tc031_tamper_guard_blocks_before_analysis_and_force_creates_bak(tmp_path: Path) -> None:
    """TC-031: tampered <id>.yaml raises ProfileTamperedError before corpus analysis; --force creates .bak."""
    profile = _sample_generated_profile()
    profile_path = tmp_path / "bill.yaml"
    save_profile(profile_path, profile)

    # Hand-edit without updating body_sha256.
    original_tampered = profile_path.read_text(encoding="utf-8").replace(
        "display_name: Bill", "display_name: TamperedBill"
    )
    profile_path.write_text(original_tampered, encoding="utf-8")

    # Simulate author build pre-check: must fail BEFORE corpus analysis runs.
    analysis_ran = False
    with pytest.raises(ProfileTamperedError) as exc_info:
        check_profile_writable(profile_path, force=False)
        analysis_ran = True  # pragma: no cover
    assert not analysis_ran
    assert exc_info.value.exit_code == 3
    assert exc_info.value.http_status == 409

    # save_profile without force also rejects and leaves tampered file untouched.
    with pytest.raises(ProfileTamperedError):
        save_profile(profile_path, profile, force=False)
    assert profile_path.read_text(encoding="utf-8") == original_tampered
    assert not Path(f"{profile_path}.bak").exists()

    # With force=True, writes .bak with tampered content and atomically replaces profile.
    save_profile(profile_path, profile, force=True)
    bak_path = Path(f"{profile_path}.bak")
    assert bak_path.is_file()
    assert "TamperedBill" in bak_path.read_text(encoding="utf-8")
    reloaded = load_profile(profile_path)
    assert reloaded["author"]["display_name"] == "Bill"
    assert reloaded["generated"]["body_sha256"] == compute_body_sha256(reloaded)


def test_tc036_drift_report_orphans_unscored_and_drifted_pins() -> None:
    """TC-036: drift_report flags orphan_edit, unscored_pin, and drifted_pin accurately."""
    generated = _sample_generated_profile()
    curated: dict[str, Any] = {
        "style_guide": {
            "sentences": "Valid override of existing rule.",
            "new_rule": {"area": "rhetoric", "rule": "Valid new rule addition."},
            "ghost_replace": "Orphan text override.",
            "ghost_remove": "$remove",
            "bad_shape": 12345,
        },
        "pins": {
            "not_a_real_feature": {"value": 1.0},
            # gen=16.0, stdev=1.2, 0.1*|gen|=1.6 -> tol=1.6; 17.5 is within tol (1.5 <= 1.6)
            "mean_sentence_length": {"value": 17.5},
            # gen=8.0, stdev=2.5, 0.1*|gen|=0.8 -> tol=2.5; 11.0 drifts by 3.0 > 2.5
            "contractions_per_1k": {"value": 11.0},
        },
        "overlays": {
            "slack": {
                "pins": {
                    # gen=16.0, tol=1.6; 10.0 drifts by 6.0 > 1.6
                    "mean_sentence_length": {"value": 10.0},
                },
            },
        },
    }
    local: dict[str, Any] = {
        "pins": {
            # gen=0.08, stdev=0.02, 0.1*|gen|=0.008 -> tol=0.02; 0.09 within tol (0.01 <= 0.02)
            "passive_rate": {"value": 0.09},
        },
    }

    report = drift_report(generated, curated, local)
    assert report.author_id == "bill"

    by_path = {issue.path: issue for issue in report.issues}
    assert by_path["curated.style_guide.ghost_replace"].kind == "orphan_edit"
    assert by_path["curated.style_guide.ghost_remove"].kind == "orphan_edit"
    assert by_path["curated.style_guide.bad_shape"].kind == "orphan_edit"
    assert "curated.style_guide.sentences" not in by_path
    assert "curated.style_guide.new_rule" not in by_path

    assert by_path["curated.pins.not_a_real_feature"].kind == "unscored_pin"
    assert "curated.pins.mean_sentence_length" not in by_path
    assert by_path["curated.pins.contractions_per_1k"].kind == "drifted_pin"
    assert by_path["curated.overlays.slack.pins.mean_sentence_length"].kind == "drifted_pin"
    assert "local.pins.passive_rate" not in by_path

    # Clean layers report zero issues.
    clean = drift_report(
        generated,
        curated={"style_guide": {"sentences": "Clean override."}},
        local=None,
    )
    assert clean.issues == ()


def test_extract_pins_ignores_invalid_entries() -> None:
    assert extract_pins({}) == {}
    assert extract_pins({"pins": "not-a-dict"}) == {}
    pins = extract_pins(
        {
            "pins": {
                "valid_full": {"value": 10, "stdev": 2},
                "valid_only_val": {"value": 5.5, "stdev": True},
                "bool_val": {"value": True},
                "str_val": {"value": "10"},
                "not_dict": 42,
            }
        }
    )
    assert pins == {
        "valid_full": {"value": 10.0, "stdev": 2.0},
        "valid_only_val": {"value": 5.5},
    }


def test_resolve_and_drift_edge_cases(tmp_path: Path) -> None:
    """Cover non-mapping validation, orphan merge no-ops, scalar/mapping replacement, and overlay validation."""
    generated = _sample_generated_profile()

    # Non-mapping top-level arguments raise ProfileError.
    with pytest.raises(ProfileError):
        resolve("not-a-dict")  # type: ignore[arg-type]
    with pytest.raises(ProfileError):
        resolve(generated, curated="bad")  # type: ignore[arg-type]
    with pytest.raises(ProfileError):
        resolve(generated, local="bad")  # type: ignore[arg-type]

    # Non-mapping overlays container or overlay entry raises ProfileError.
    with pytest.raises(ProfileError):
        resolve(generated, curated={"overlays": "bad"}, overlays=("slack",))
    with pytest.raises(ProfileError):
        resolve(generated, curated={"overlays": {"slack": "bad"}}, overlays=("slack",))

    # Non-mapping style_guide, list op on non-list, mapping onto list raise ProfileError.
    with pytest.raises(ProfileError):
        resolve(generated, curated={"style_guide": "invalid"})
    with pytest.raises(ProfileError):
        resolve(generated, curated={"author": {"display_name": {"$add": ["x"]}}})
    with pytest.raises(ProfileError):
        resolve(generated, curated={"author": {"aliases": {"not_op": 1}}})

    # Scalar replacing mapping clears child provenance; orphan style_guide edits are ignored in merge.
    merged, prov = resolve(
        {"author": {"id": "bill"}, "meta": {"a": 1, "b": 2}},
        curated={
            "meta": "flat",
            "style_guide": {
                "missing_str": "ignored",
                "missing_rm": "$remove",
                "bad_val": 99,
                "added": {"area": "voice", "rule": "Added rule."},
            },
        },
        overlays=("nonexistent",),
    )
    assert merged["meta"] == "flat"
    assert prov["meta"] == "curated"
    assert "meta.a" not in prov
    assert merged["style_guide"] == [{"id": "added", "area": "voice", "rule": "Added rule."}]

    # Drift report ignores non-dict pin config / non-numeric pin value and inspects local overlays.
    report = drift_report(
        generated,
        curated={"pins": {"mean_sentence_length": "bad", "passive_rate": {"value": True}}},
        local={
            "overlays": {
                "email": {"pins": {"mean_sentence_length": {"value": 30.0}}},
            }
        },
    )
    assert len(report.issues) == 1
    assert report.issues[0].path == "local.overlays.email.pins.mean_sentence_length"
    assert report.issues[0].kind == "drifted_pin"

    # Directory in place of companion file raises ProfileError.
    profile_path = tmp_path / "bill.yaml"
    save_profile(profile_path, generated)
    (tmp_path / "bill.curated.yaml").mkdir()
    with pytest.raises(ProfileError):
        load_resolved_profile(profile_path)
