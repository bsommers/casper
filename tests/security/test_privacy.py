"""Security tests for private author data isolation and atomic 0o600 local writes (TC-030)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml

from casper.errors import ProfileError, SecurityError
from casper.layers import load_resolved_profile, write_local_email
from casper.profile import build_profile, load_profile, save_profile


def _write_sample_doc(path: Path) -> Path:
    body = " ".join(
        ["We ship deterministic code with verified contracts every release cycle."] * 18
    )
    path.write_text(f"---\ntitle: Sample\nauthor: Bill\n---\n\n{body}\n", encoding="utf-8")
    return path


def test_tc030_write_local_email_atomic_0600_and_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-030: write_local_email uses os.open(O_WRONLY|O_CREAT|O_EXCL, 0o600) and preserves local keys."""
    authors_dir = tmp_path / "authors"
    open_calls: list[tuple[Any, int, int]] = []
    real_open = os.open

    def spy_open(path: Any, flags: int, mode: int = 0o777, *args: Any, **kwargs: Any) -> int:
        open_calls.append((path, flags, mode))
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)

    local_path = write_local_email(authors_dir, "bill", "secret@example.invalid")
    assert local_path == authors_dir / "bill.local.yaml"
    assert local_path.is_file()

    # Verify atomic creation flags & mode 0o600 (never transiently 0o644).
    assert len(open_calls) == 1
    tmp_opened, flags, mode = open_calls[0]
    assert ".tmp." in str(tmp_opened)
    assert flags == (os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    assert mode == 0o600

    # Verify final file mode is strictly 0o600 and no temp files remain.
    assert stat.S_IMODE(local_path.stat().st_mode) == 0o600
    assert [p for p in authors_dir.iterdir() if ".tmp." in p.name] == []

    loaded = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    assert loaded == {"author": {"email": "secret@example.invalid"}}

    # Add extra local settings (consent, pins, overlays), then call write_local_email again.
    loaded["author"]["consent"] = "private-consent-note"
    loaded["pins"] = {"mean_sentence_length": {"value": 15.0}}
    loaded["overlays"] = {"slack": {"pins": {"mean_sentence_length": {"value": 12.0}}}}
    local_path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")

    local_path_2 = write_local_email(authors_dir, "bill", "updated@example.invalid")
    assert local_path_2 == local_path
    assert stat.S_IMODE(local_path_2.stat().st_mode) == 0o600
    assert [p for p in authors_dir.iterdir() if ".tmp." in p.name] == []

    reloaded = yaml.safe_load(local_path_2.read_text(encoding="utf-8"))
    assert reloaded["author"]["email"] == "updated@example.invalid"
    assert reloaded["author"]["consent"] == "private-consent-note"
    assert reloaded["pins"] == {"mean_sentence_length": {"value": 15.0}}
    assert reloaded["overlays"] == {"slack": {"pins": {"mean_sentence_length": {"value": 12.0}}}}


def test_tc030_generated_profile_never_contains_email_or_consent(tmp_path: Path) -> None:
    """TC-030: tracked <id>.yaml stays free of private email/consent while local holds private fields."""
    doc = _write_sample_doc(tmp_path / "doc.md")
    authors_dir = tmp_path / "authors"

    profile = build_profile("bill", "Bill", [doc], min_words=150)
    profile_path = save_profile(authors_dir / "bill.yaml", profile)
    write_local_email(authors_dir, "bill", "private@example.invalid")

    raw_generated = profile_path.read_text(encoding="utf-8")
    assert "private@example.invalid" not in raw_generated
    assert "email" not in load_profile(profile_path)["author"]
    assert "consent" not in load_profile(profile_path)["author"]

    resolved, prov = load_resolved_profile(profile_path)
    assert resolved["author"]["email"] == "private@example.invalid"
    assert prov["author.email"] == "local"
    # On-disk tracked profile still has zero private data.
    assert "private@example.invalid" not in profile_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad_id",
    ["", "   ", "../escape", "sub/bill", "sub\\bill", "..", ".", "bill\x00x"],
)
def test_tc030_write_local_email_rejects_path_traversal(tmp_path: Path, bad_id: str) -> None:
    authors_dir = tmp_path / "authors"
    with pytest.raises(SecurityError):
        write_local_email(authors_dir, bad_id, "secret@example.invalid")
    assert not any(tmp_path.rglob("*.local.yaml"))


def test_write_local_email_cleans_up_temp_on_failure_and_validates_author_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authors_dir = tmp_path / "authors"
    authors_dir.mkdir()
    (authors_dir / "bad.local.yaml").write_text("author: not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        write_local_email(authors_dir, "bad", "secret@example.invalid")

    def boom_replace(src: Any, dst: Any) -> None:
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", boom_replace)
    with pytest.raises(OSError, match="simulated disk full"):
        write_local_email(authors_dir, "bill", "secret@example.invalid")
    assert [p for p in authors_dir.iterdir() if ".tmp." in p.name] == []
    assert not (authors_dir / "bill.local.yaml").exists()


@pytest.mark.parametrize("backend_name", ["claude", "agy"])
def test_tc030_cli_prompt_excludes_author_sources_email_consent_and_local_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
) -> None:
    """TC-030: CLI prompts never include email, consent, author block, sources, or local provenance."""
    from casper import facts as facts_mod
    from casper import llm, planner
    from casper.libraries import load_libraries
    from casper.models import BackendKind, Constraints, PersonaKind

    doc = _write_sample_doc(tmp_path / "secret_corpus_file_alpha.md")
    authors_dir = tmp_path / "authors"

    profile = build_profile(
        "bill",
        "Bill PrivateName",
        [doc],
        aliases=["William AliasSecret"],
        min_words=150,
    )
    profile_path = save_profile(authors_dir / "bill.yaml", profile)
    write_local_email(authors_dir, "bill", "topsecret@example.invalid")

    # Add private consent, local style_guide override, local pin, local exemplar, and local overlay.
    local_path = authors_dir / "bill.local.yaml"
    local_data = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    local_data["author"]["consent"] = "PRIVATE_CONSENT_TOKEN_999"
    local_data["style_guide"] = {"voice": "LOCAL_PRIVATE_STYLE_RULE_XYZ"}
    local_data["pins"] = {"mean_sentence_length": {"value": 99.123}}
    local_data["exemplars"] = {"openers": {"$replace": ["LOCAL_PRIVATE_OPENER_ABC"]}}
    local_data["overlays"] = {
        "slack": {
            "style_guide": {"sentences": "LOCAL_OVERLAY_SECRET_RULE_777"},
        }
    }
    local_path.write_text(yaml.safe_dump(local_data, sort_keys=False), encoding="utf-8")

    # Also add a non-local curated rule to confirm public style guidance IS preserved.
    curated_path = authors_dir / "bill.curated.yaml"
    curated_path.write_text(
        yaml.safe_dump(
            {"style_guide": {"lexical": "CURATED_PUBLIC_LEXICAL_RULE"}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    resolved, prov = load_resolved_profile(profile_path, overlays=("slack",))
    libs = load_libraries()
    fact_model = facts_mod.ingest(notes="Status: Rollout is on track at 95%.")
    plan = planner.plan_structure(fact_model, libs.structures["status_update"])
    adapted = planner.adapt(
        plan,
        libs.personas[(PersonaKind.SOURCE, "developer")],
        libs.personas[(PersonaKind.TARGET, "management")],
        libs.glossary,
    )

    backend = BackendKind(backend_name)
    realizer = llm.CliAgentRealizer(backend, libs, timeout=10)
    prompt = realizer.build_prompt(adapted, resolved, Constraints(), provenance=prov)

    # Curated non-local guidance survives.
    assert "CURATED_PUBLIC_LEXICAL_RULE" in prompt

    # All private / local / author / source data is strictly excluded.
    forbidden_substrings = (
        "topsecret@example.invalid",
        "PRIVATE_CONSENT_TOKEN_999",
        "Bill PrivateName",
        "William AliasSecret",
        "secret_corpus_file_alpha",
        "LOCAL_PRIVATE_STYLE_RULE_XYZ",
        "LOCAL_PRIVATE_OPENER_ABC",
        "LOCAL_OVERLAY_SECRET_RULE_777",
        "99.123",
    )
    for secret in forbidden_substrings:
        assert secret not in prompt, f"Private string leaked into {backend_name} prompt: {secret}"

    # Verify end-to-end dumped prompt through fake_agent.py as well.
    fake_agent = Path(__file__).resolve().parents[1] / "fakes" / "fake_agent.py"
    dump_file = tmp_path / f"dumped_{backend_name}.txt"
    env_var = "CASPER_CLAUDE_CLI" if backend == BackendKind.CLAUDE else "CASPER_AGY_CLI"
    monkeypatch.setenv(env_var, str(fake_agent))
    monkeypatch.setenv("CASPER_FAKE_MODE", "good")
    monkeypatch.setenv("CASPER_FAKE_DUMP_PROMPT", str(dump_file))

    realizer.realize(
        adapted,
        resolved,
        Constraints(),
        libs.modalities["slack"],
        provenance=prov,
    )
    dumped = dump_file.read_text(encoding="utf-8")
    for secret in forbidden_substrings:
        assert secret not in dumped, f"Private string leaked in live subprocess prompt: {secret}"


def test_tc030_cli_author_build_isolates_email_in_0600_local_yaml(tmp_path: Path) -> None:
    """TC-030: CLI `author build --email` isolates private email in 0o600 .local.yaml only."""
    from casper import cli

    doc = _write_sample_doc(tmp_path / "carol_doc.md")
    authors_dir = tmp_path / "authors"
    secret_email = "carol-secret@example.invalid"

    rc = cli.main(
        [
            "author",
            "--authors-dir",
            str(authors_dir),
            "build",
            "--id",
            "carol",
            "--name",
            "Carol",
            "--email",
            secret_email,
            str(doc),
        ]
    )
    assert rc == 0

    local_path = authors_dir / "carol.local.yaml"
    public_path = authors_dir / "carol.yaml"
    assert local_path.is_file()
    assert stat.S_IMODE(local_path.stat().st_mode) == 0o600
    assert secret_email in local_path.read_text(encoding="utf-8")

    public_text = public_path.read_text(encoding="utf-8")
    assert secret_email not in public_text
    assert "email:" not in public_text
