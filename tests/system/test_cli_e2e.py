"""System E2E tests for the `casper` CLI and public lazy API (TC-018)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import yaml

import casper
from casper import cli, commands
from casper.errors import InputError, ProfileError, SecurityError

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS_NOTES = REPO_ROOT / "tests" / "fixtures" / "status_notes.md"
FAKE_AGENT = REPO_ROOT / "tests" / "fakes" / "fake_agent.py"


@pytest.fixture(autouse=True)
def _ensure_fake_agent_executable() -> None:
    mode = FAKE_AGENT.stat().st_mode
    if not (mode & stat.S_IXUSR):
        FAKE_AGENT.chmod(mode | stat.S_IXUSR)


def _write_alice_doc(path: Path, idx: int) -> Path:
    body = " ".join(
        [
            f"We ship fast code (batch {idx}).",
            "Short sentences work!",
            "Can we measure latency?",
            "Yes, we track SLOs daily.",
            "It isn't luck; it's discipline!",
        ]
        * 12
    )
    path.write_text(
        f"---\ntitle: \"Alice Note {idx}\"\nauthor: \"Alice Tester\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _write_bob_doc(path: Path, idx: int) -> Path:
    sentence = (
        f"Consequently, although the migration schedule for phase {idx} remained complex, "
        "the engineering organization documented every architectural constraint carefully; "
        "moreover, because downstream services depended upon deterministic verification, "
        "comprehensive integration benchmarks were executed prior to deployment."
    )
    body = " ".join([sentence] * 7)
    path.write_text(
        f"---\ntitle: \"Bob Report {idx}\"\nauthor: \"Bob Tester\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_tc018_write_out_and_trace_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_file = tmp_path / "draft.txt"
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
            "--input",
            str(STATUS_NOTES),
            "--out",
            str(out_file),
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert out_file.is_file()
    file_text = out_file.read_text(encoding="utf-8")
    assert captured.out.rstrip("\n") == file_text.rstrip("\n")
    assert "[casper]" in captured.err

    trace_path = tmp_path / "draft.txt.trace.json"
    assert trace_path.is_file()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    for key in ("text", "validation", "fact_trace", "record", "facts", "backend"):
        assert key in trace
    assert trace["text"] == file_text
    assert trace["validation"]["ok"] is True
    assert trace["backend"]["used"] == "rules"


def test_tc018_write_brief_yaml_cli_overrides_and_fact_overrides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    brief_path = tmp_path / "brief.yaml"
    brief_path.write_text(
        yaml.safe_dump(
            {
                "structure": "status_update",
                "modality": "email",
                "source": "developer",
                "target": "management",
                "inputs": [str(STATUS_NOTES)],
                "seed": 1,
                "topic": "Initial Topic",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out_file = tmp_path / "overridden.txt"
    rc = cli.main(
        [
            "write",
            "--brief",
            str(brief_path),
            "--modality",
            "slack",
            "--seed",
            "7",
            "--fact-override",
            "f001=risk",
            "--fact-override",
            "f002=metric",
            "--out",
            str(out_file),
            "--json",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["record"]["selectors"]["modality"] == "slack"
    assert payload["record"]["seed"] == 7
    fact_kinds = {f["id"]: f["kind"] for f in payload["facts"]}
    assert fact_kinds["f001"] == "risk"
    assert fact_kinds["f002"] == "metric"


def test_tc018_write_dry_run_list_options_and_backend_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --dry-run (text & JSON)
    rc_dry = cli.main(["write", "--input", str(STATUS_NOTES), "--dry-run"])
    out_dry = capsys.readouterr()
    assert rc_dry == 0
    assert "[f001]" in out_dry.out

    rc_dry_json = cli.main(["write", "--input", str(STATUS_NOTES), "--dry-run", "--json"])
    out_dry_json = capsys.readouterr()
    assert rc_dry_json == 0
    dry_data = json.loads(out_dry_json.out)
    assert dry_data["facts"]

    # --list-options (text & JSON)
    empty_authors = tmp_path / "empty_authors"
    rc_list = cli.main(["write", "--list-options", "--authors-dir", str(empty_authors)])
    out_list = capsys.readouterr()
    assert rc_list == 0
    assert "Structures:" in out_list.out
    assert "Backends:" in out_list.out

    rc_list_json = cli.main(
        ["write", "--list-options", "--json", "--authors-dir", str(empty_authors)]
    )
    out_list_json = capsys.readouterr()
    assert rc_list_json == 0
    opts = json.loads(out_list_json.out)
    assert {"personas", "structures", "modalities", "authors", "backends"} <= set(opts)

    # --backend-status (text & JSON) with fake_agent.py
    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "good")
    monkeypatch.setenv("CASPER_FAKE_VERSION", "fake-agent 1.2.3")

    rc_bs = cli.main(["write", "--backend-status"])
    out_bs = capsys.readouterr()
    assert rc_bs == 0
    assert "claude: ready" in out_bs.out
    assert "agy: ready" in out_bs.out

    rc_bs_json = cli.main(["write", "--backend-status", "--json"])
    out_bs_json = capsys.readouterr()
    assert rc_bs_json == 0
    bs_data = json.loads(out_bs_json.out)
    assert bs_data["backends"]["claude"]["available"] is True
    assert bs_data["backends"]["agy"]["available"] is True
    assert "fake-agent 1.2.3" in bs_data["backends"]["claude"]["version"]


def test_tc018_backend_claude_fail_fallback_and_no_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "fail")

    out_file = tmp_path / "fallback.txt"
    rc_fb = cli.main(
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
            "--input",
            str(STATUS_NOTES),
            "--backend",
            "claude",
            "--out",
            str(out_file),
            "--json",
        ]
    )
    cap_fb = capsys.readouterr()
    assert rc_fb == 0
    fb_payload = json.loads(cap_fb.out)
    assert fb_payload["backend"]["used"] == "rules"
    assert "[casper] warning:" in cap_fb.err

    rc_nofb = cli.main(
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
            "--input",
            str(STATUS_NOTES),
            "--backend",
            "claude",
            "--no-fallback",
        ]
    )
    cap_nofb = capsys.readouterr()
    assert rc_nofb == 2
    assert "Error [backend-error]" in cap_nofb.err


def test_tc018_backend_claude_invent_fails_validation_exit_1(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "invent")

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
            "--input",
            str(STATUS_NOTES),
            "--backend",
            "claude",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    payload = json.loads(captured.out)
    assert payload["validation"]["ok"] is False
    assert payload["backend"]["used"] == "claude"


def test_tc018_author_full_lifecycle_and_tamper_guard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    authors_dir = tmp_path / "authors"
    doc1 = _write_alice_doc(tmp_path / "alice_1.md", 1)
    doc2 = _write_alice_doc(tmp_path / "alice_2.md", 2)
    doc3 = _write_bob_doc(tmp_path / "bob_1.md", 1)
    doc4 = _write_bob_doc(tmp_path / "bob_2.md", 2)

    # build alice & bob
    rc_a = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "build",
            "--id",
            "alice",
            "--name",
            "Alice Tester",
            "--alias",
            "A. Tester",
            str(doc1),
            str(doc2),
        ]
    )
    assert rc_a == 0
    assert "Built author profile 'alice'" in capsys.readouterr().out

    rc_b = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "build",
            "--id",
            "bob",
            "--name",
            "Bob Tester",
            str(doc3),
            str(doc4),
        ]
    )
    assert rc_b == 0
    assert "Built author profile 'bob'" in capsys.readouterr().out

    # author list [--json]
    assert cli.main(["author", "--authors-dir", str(authors_dir), "list"]) == 0
    list_text = capsys.readouterr().out
    assert "alice" in list_text and "bob" in list_text

    assert cli.main(["author", "--authors-dir", str(authors_dir), "list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert {item["id"] for item in listed} == {"alice", "bob"}

    # author inspect [--json]
    assert cli.main(["author", "--authors-dir", str(authors_dir), "inspect", "alice"]) == 0
    assert "Author: alice (Alice Tester)" in capsys.readouterr().out

    assert (
        cli.main(["author", "--authors-dir", str(authors_dir), "inspect", "alice", "--json"]) == 0
    )
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["id"] == "alice"
    assert inspected["corpus"]["document_count"] == 2

    # author show [--resolved] [--overlay slack] [--json]
    assert cli.main(["author", "--authors-dir", str(authors_dir), "show", "alice"]) == 0
    assert "Alice Tester" in capsys.readouterr().out

    assert (
        cli.main(
            [
                "author",
                "--authors-dir",
                str(authors_dir),
                "show",
                "alice",
                "--resolved",
                "--overlay",
                "slack",
                "--json",
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["author"]["id"] == "alice"

    # author score [--raw] [--overlay slack] [--json]
    assert (
        cli.main(["author", "--authors-dir", str(authors_dir), "score", "alice", str(doc1)]) == 0
    )
    assert "Voice score:" in capsys.readouterr().out

    assert (
        cli.main(
            [
                "author",
                "--authors-dir",
                str(authors_dir),
                "score",
                "alice",
                str(doc1),
                "--raw",
                "--json",
            ]
        )
        == 0
    )
    scored_raw = json.loads(capsys.readouterr().out)
    assert 0.0 <= scored_raw["overall"] <= 100.0

    assert (
        cli.main(
            [
                "author",
                "--authors-dir",
                str(authors_dir),
                "score",
                "alice",
                str(doc1),
                "--overlay",
                "slack",
                "--json",
            ]
        )
        == 0
    )
    scored_overlay = json.loads(capsys.readouterr().out)
    assert 0.0 <= scored_overlay["overall"] <= 100.0

    # author diff [--json]
    assert cli.main(["author", "--authors-dir", str(authors_dir), "diff", "alice", "bob"]) == 0
    assert "Diff alice vs bob:" in capsys.readouterr().out

    assert (
        cli.main(["author", "--authors-dir", str(authors_dir), "diff", "alice", "bob", "--json"])
        == 0
    )
    diffed = json.loads(capsys.readouterr().out)
    assert diffed["author_a"] == "alice"
    assert diffed["author_b"] == "bob"
    assert len(diffed["feature_deltas"]) == 32
    assert any(d["normalized_delta"] != 0.0 for d in diffed["feature_deltas"])

    # Tamper alice.yaml without updating body_sha256 -> exit 3, then --force -> exit 0 + .bak
    alice_yaml = authors_dir / "alice.yaml"
    original_text = alice_yaml.read_text(encoding="utf-8")
    assert "display_name: Alice Tester" in original_text
    alice_yaml.write_text(
        original_text.replace("display_name: Alice Tester", "display_name: Tampered Alice"),
        encoding="utf-8",
    )

    rc_tamper = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "build",
            "--id",
            "alice",
            "--name",
            "Alice Tester",
            str(doc1),
            str(doc2),
        ]
    )
    err_tamper = capsys.readouterr().err
    assert rc_tamper == 3
    assert "profile-tampered" in err_tamper

    rc_force = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "build",
            "--id",
            "alice",
            "--name",
            "Alice Tester",
            "--force",
            str(doc1),
            str(doc2),
        ]
    )
    assert rc_force == 0
    capsys.readouterr()
    bak_path = authors_dir / "alice.yaml.bak"
    assert bak_path.is_file()
    assert "Tampered Alice" in bak_path.read_text(encoding="utf-8")


def test_tc018_serve_non_loopback_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["serve", "--host", "0.0.0.0"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "security-error" in captured.err


def test_tc018_lazy_top_level_imports() -> None:
    expected_names = (
        "write_draft",
        "generate",
        "extract_facts",
        "score_draft",
        "list_options",
        "backend_status",
        "author_build",
        "author_inspect",
        "author_show",
        "author_list",
        "author_diff",
        "Brief",
        "Result",
        "CasperError",
        "ProfileTamperedError",
    )
    for name in expected_names:
        assert getattr(casper, name) is not None
    assert casper.generate is casper.write_draft



def test_cli_write_error_branches_and_plain_text_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Missing required flags -> exit 2
    rc_missing_flags = cli.main(["write", "--input", str(STATUS_NOTES)])
    err_missing_flags = capsys.readouterr().err
    assert rc_missing_flags == 2
    assert "--structure" in err_missing_flags
    assert "--modality" in err_missing_flags

    # --brief <missing.yaml> -> exit 2
    missing_brief = tmp_path / "does_not_exist.yaml"
    rc_missing_brief = cli.main(["write", "--brief", str(missing_brief)])
    err_missing_brief = capsys.readouterr().err
    assert rc_missing_brief == 2
    assert "Brief file not found" in err_missing_brief

    # --brief <invalid_yaml.yaml> -> exit 2
    invalid_yaml = tmp_path / "invalid.yaml"
    invalid_yaml.write_text("structure: [unclosed\n", encoding="utf-8")
    rc_invalid_yaml = cli.main(["write", "--brief", str(invalid_yaml)])
    err_invalid_yaml = capsys.readouterr().err
    assert rc_invalid_yaml == 2
    assert "Invalid YAML in brief file" in err_invalid_yaml

    # --brief <list_yaml.yaml> (non-mapping YAML) -> exit 2
    list_yaml = tmp_path / "list.yaml"
    list_yaml.write_text("- status_update\n- slack\n", encoding="utf-8")
    rc_list_yaml = cli.main(["write", "--brief", str(list_yaml)])
    err_list_yaml = capsys.readouterr().err
    assert rc_list_yaml == 2
    assert "must contain a YAML mapping" in err_list_yaml

    # --brief with non-dict fact_overrides -> exit 2
    bad_overrides_type = tmp_path / "bad_overrides_type.yaml"
    bad_overrides_type.write_text(
        yaml.safe_dump(
            {
                "structure": "status_update",
                "modality": "slack",
                "source": "developer",
                "target": "management",
                "fact_overrides": ["f001=risk"],
            }
        ),
        encoding="utf-8",
    )
    rc_bad_ov_type = cli.main(["write", "--brief", str(bad_overrides_type)])
    err_bad_ov_type = capsys.readouterr().err
    assert rc_bad_ov_type == 2
    assert "must be a mapping" in err_bad_ov_type

    # --brief with unknown kind in fact_overrides -> exit 2
    bad_overrides_kind = tmp_path / "bad_overrides_kind.yaml"
    bad_overrides_kind.write_text(
        yaml.safe_dump(
            {
                "structure": "status_update",
                "modality": "slack",
                "source": "developer",
                "target": "management",
                "fact_overrides": {"f001": "bogus_kind"},
            }
        ),
        encoding="utf-8",
    )
    rc_bad_ov_kind = cli.main(["write", "--brief", str(bad_overrides_kind)])
    err_bad_ov_kind = capsys.readouterr().err
    assert rc_bad_ov_kind == 2
    assert "Unknown fact kind" in err_bad_ov_kind

    # Plain-text --list-options, --backend-status (including unavailable), --dry-run -> exit 0
    empty_authors = tmp_path / "empty_authors"
    rc_opts = cli.main(["write", "--list-options", "--authors-dir", str(empty_authors)])
    out_opts = capsys.readouterr().out
    assert rc_opts == 0
    assert "Authors: (none)" in out_opts
    assert "Structures:" in out_opts

    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(tmp_path / "missing_claude_cli"))
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "good")
    monkeypatch.setenv("CASPER_FAKE_VERSION", "fake-agent 2.0.0")
    rc_bs = cli.main(["write", "--backend-status"])
    out_bs = capsys.readouterr().out
    assert rc_bs == 0
    assert "claude: unavailable" in out_bs
    assert "agy: ready" in out_bs

    rc_dry = cli.main(["write", "--input", str(STATUS_NOTES), "--dry-run"])
    out_dry = capsys.readouterr().out
    assert rc_dry == 0
    assert "[f001]" in out_dry and "salience=" in out_dry


def test_cli_author_plain_outputs_drift_and_command_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_dir = tmp_path / "no_authors"
    empty_dir.mkdir()
    rc_empty_list = cli.main(["author", "--authors-dir", str(empty_dir), "list"])
    out_empty_list = capsys.readouterr().out
    assert rc_empty_list == 0
    assert "(no author profiles found)" in out_empty_list

    authors_dir = tmp_path / "authors"
    doc_a1 = _write_alice_doc(tmp_path / "a1.md", 1)
    doc_a2 = _write_alice_doc(tmp_path / "a2.md", 2)
    doc_b1 = _write_bob_doc(tmp_path / "b1.md", 1)
    doc_b2 = _write_bob_doc(tmp_path / "b2.md", 2)

    assert (
        cli.main(
            [
                "author",
                "--authors-dir",
                str(authors_dir),
                "build",
                "--id",
                "alice",
                "--name",
                "Alice Tester",
                str(doc_a1),
                str(doc_a2),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            [
                "author",
                "--authors-dir",
                str(authors_dir),
                "build",
                "--id",
                "bob",
                "--name",
                "Bob Tester",
                str(doc_b1),
                str(doc_b2),
            ]
        )
        == 0
    )
    capsys.readouterr()

    # Curated layer with orphan edit -> plain-text inspect prints drift issues
    curated_path = authors_dir / "alice.curated.yaml"
    curated_path.write_text(
        yaml.safe_dump({"style_guide": {"nonexistent_rule": "Do not do this."}}),
        encoding="utf-8",
    )
    rc_inspect = cli.main(["author", "--authors-dir", str(authors_dir), "inspect", "alice"])
    out_inspect = capsys.readouterr().out
    assert rc_inspect == 0
    assert "Curated layer: True" in out_inspect
    assert "Drift issues: 1" in out_inspect
    assert "[orphan_edit] curated.style_guide.nonexistent_rule:" in out_inspect

    # author show (plain YAML output, no --json)
    rc_show = cli.main(["author", "--authors-dir", str(authors_dir), "show", "alice"])
    out_show = capsys.readouterr().out
    assert rc_show == 0
    loaded_show = yaml.safe_load(out_show)
    assert isinstance(loaded_show, dict)
    assert loaded_show["author"]["id"] == "alice"

    # author score (plain text output with largest_gaps printed)
    rc_score = cli.main(
        ["author", "--authors-dir", str(authors_dir), "score", "alice", str(doc_b1)]
    )
    out_score = capsys.readouterr().out
    assert rc_score == 0
    assert "Voice score:" in out_score
    assert "  - " in out_score

    # author diff (plain text output)
    rc_diff = cli.main(["author", "--authors-dir", str(authors_dir), "diff", "alice", "bob"])
    out_diff = capsys.readouterr().out
    assert rc_diff == 0
    assert "Diff alice vs bob:" in out_diff
    assert "(norm=" in out_diff

    # commands.author_build with invalid author ID -> SecurityError
    with pytest.raises(SecurityError):
        commands.author_build(
            "../bad",
            "Bad Author",
            [doc_a1],
            authors_dir=authors_dir,
        )

    # commands.score_draft with is_text=True and empty/whitespace text -> InputError
    with pytest.raises(InputError):
        commands.score_draft("alice", "   \n\t  ", authors_dir=authors_dir, is_text=True)

    # commands.author_inspect with malformed .curated.yaml -> ProfileError
    curated_path.write_text("style_guide: [broken\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        commands.author_inspect("alice", authors_dir=authors_dir)

    curated_path.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        commands.author_inspect("alice", authors_dir=authors_dir)
