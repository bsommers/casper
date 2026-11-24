"""Integration tests for optional `claude` & `agy` CLI writers and status probes (TC-041, TC-042)."""

from __future__ import annotations

import dataclasses
import stat
from pathlib import Path
from typing import Any

import pytest

from casper import facts as facts_mod
from casper import llm, planner, validator
from casper.errors import BackendError, InputError
from casper.libraries import load_libraries
from casper.models import (
    BackendKind,
    CheckLevel,
    Constraints,
    FidelityMode,
    PersonaKind,
)

FAKE_AGENT = Path(__file__).resolve().parents[1] / "fakes" / "fake_agent.py"


def _make_plan() -> tuple[Any, Any, Any, Any]:
    libs = load_libraries()
    notes = (
        "Status: Migration is on track with 98% pass rate.\n"
        "Progress: Edge proxy rollout completed in staging on 2026-10-12.\n"
        "Risk: Legacy cache invalidation remains a minor risk.\n"
        "Next: Production cutover is scheduled for Friday.\n"
        "Ask: Please approve the production cutover window.\n"
    )
    fact_model = facts_mod.ingest(notes=notes)
    structure = libs.structures["status_update"]
    modality = libs.modalities["slack"]
    source = libs.personas[(PersonaKind.SOURCE, "developer")]
    target = libs.personas[(PersonaKind.TARGET, "management")]
    plan = planner.plan_structure(fact_model, structure)
    adapted = planner.adapt(plan, source, target, libs.glossary)
    return libs, fact_model, adapted, modality


@pytest.fixture(autouse=True)
def _ensure_fake_executable() -> None:
    mode = FAKE_AGENT.stat().st_mode
    if not (mode & stat.S_IXUSR):
        FAKE_AGENT.chmod(mode | stat.S_IXUSR)


def _env_var_for(backend: BackendKind) -> str:
    return "CASPER_CLAUDE_CLI" if backend == BackendKind.CLAUDE else "CASPER_AGY_CLI"


@pytest.mark.parametrize("backend", [BackendKind.CLAUDE, BackendKind.AGY])
@pytest.mark.parametrize(
    ("mode", "expected_ok", "expected_code", "expected_level"),
    [
        ("good", True, None, None),
        ("invent", False, "unsupported-number", CheckLevel.ERROR),
        ("rename", False, "unsupported-name", CheckLevel.ERROR),
        ("polarity", False, "polarity-mismatch", CheckLevel.ERROR),
        ("uncited", False, "untraced", CheckLevel.ERROR),
        ("reword", True, "reworded", CheckLevel.WARNING),
    ],
)
def test_tc041_fake_cli_draft_modes_validated(
    backend: BackendKind,
    mode: str,
    expected_ok: bool,
    expected_code: str | None,
    expected_level: CheckLevel | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-041: good/invent/rename/polarity/uncited/reword validated in ASSISTED mode for claude & agy."""
    libs, fact_model, adapted, modality = _make_plan()
    monkeypatch.setenv(_env_var_for(backend), str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", mode)

    realizer = llm.CliAgentRealizer(backend, libs, timeout=15)
    constraints = Constraints(max_words=modality.max_words, max_chars=modality.max_chars, seed=0)
    draft = realizer.realize(adapted, None, constraints, modality)

    assert draft.backend == backend
    assert draft.meta["backend"] == str(backend)
    assert len(draft.meta["prompt_sha256"]) == 64
    assert len(draft.meta["response_sha256"]) == 64

    validation = validator.validate(
        draft,
        adapted,
        fact_model,
        None,
        constraints,
        modality,
        fidelity_mode=FidelityMode.ASSISTED,
        glossary=libs.glossary,
    )
    assert validation.ok is expected_ok, f"Unexpected findings: {validation.findings}"
    if expected_code is not None:
        matching = [f for f in validation.findings if f.code == expected_code]
        assert matching, f"Expected finding {expected_code}, got {validation.findings}"
        assert all(f.level == expected_level for f in matching)


@pytest.mark.parametrize("backend", [BackendKind.CLAUDE, BackendKind.AGY])
@pytest.mark.parametrize("mode", ["fail", "empty", "hang"])
def test_tc041_fake_cli_failure_modes_raise_backend_error(
    backend: BackendKind,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-041: fail/empty/hang raise BackendError cleanly for both claude & agy."""
    libs, _, adapted, modality = _make_plan()
    monkeypatch.setenv(_env_var_for(backend), str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", mode)
    monkeypatch.setenv("CASPER_FAKE_SLEEP", "3.0")

    timeout = 1 if mode == "hang" else 10
    realizer = llm.CliAgentRealizer(backend, libs, timeout=timeout)
    constraints = Constraints(max_words=modality.max_words, max_chars=modality.max_chars, seed=0)

    with pytest.raises(BackendError):
        realizer.realize(adapted, None, constraints, modality)


@pytest.mark.parametrize("backend", [BackendKind.CLAUDE, BackendKind.AGY])
def test_tc041_isolation_argv_model_cwd_and_env_allowlist(
    backend: BackendKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify exact argv flags, fresh empty temp cwd, model forwarding, and env stripping."""
    libs, _, adapted, modality = _make_plan()
    monkeypatch.setenv("UNRELATED_SECRET_TOKEN", "should-never-leak")
    monkeypatch.delenv("CASPER_CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CASPER_AGY_MODEL", raising=False)

    captured: dict[str, Any] = {}

    def spy_runner(
        argv: Any,
        cwd: Path,
        timeout: float,
        env: Any,
    ) -> tuple[int, str, str]:
        captured["argv"] = list(argv)
        captured["cwd"] = cwd
        captured["cwd_entries"] = list(cwd.iterdir())
        captured["timeout"] = timeout
        captured["env"] = dict(env)
        first_fact = adapted.sections[0].facts[0]
        return (
            0,
            f"```markdown\n## {adapted.sections[0].section.name}\n{first_fact.text} [{first_fact.id}]\n```",
            "",
        )

    realizer = llm.CliAgentRealizer(
        backend,
        libs,
        timeout=42,
        model="test-model-v1",
        runner=spy_runner,
    )
    draft = realizer.realize(adapted, None, Constraints(), modality)

    if backend == BackendKind.AGY:
        assert captured["argv"][1:7] == [
            "--output-format",
            "text",
            "--model",
            "test-model-v1",
            "-p",
            captured["argv"][-1],
        ]
    else:
        assert captured["argv"][1:6] == ["-p", "--output-format", "text", "--model", "test-model-v1"]
    assert captured["cwd_entries"] == []
    assert captured["timeout"] == 42.0
    assert "UNRELATED_SECRET_TOKEN" not in captured["env"]
    assert draft.meta["model"] == "test-model-v1"
    assert draft.sections


def test_cli_realizer_validation_and_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    libs, _, adapted, modality = _make_plan()
    with pytest.raises(InputError):
        llm.CliAgentRealizer(BackendKind.RULES, libs)
    with pytest.raises(InputError):
        llm.CliAgentRealizer(BackendKind.CLAUDE, libs, timeout=0)

    monkeypatch.setenv("CASPER_CLAUDE_CLI", "/nonexistent/casper-missing-cli")
    realizer = llm.CliAgentRealizer(BackendKind.CLAUDE, libs)
    with pytest.raises(BackendError, match="not found"):
        realizer.realize(adapted, None, Constraints(), modality)


def test_tc042_status_both_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-042: llm.status() reports rules, claude, and agy all ready when CLIs succeed."""
    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "good")
    monkeypatch.setenv("CASPER_FAKE_VERSION", "2.3.4-fake")

    report = llm.status(timeout=5.0)
    assert report.backends["rules"].available is True
    assert report.backends["claude"].available is True
    assert report.backends["claude"].version == "2.3.4-fake"
    assert report.backends["agy"].available is True
    assert report.backends["agy"].version == "2.3.4-fake"


def test_tc042_status_one_missing_and_one_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-042: llm.status() handles missing executable and timed-out CLI cleanly."""
    monkeypatch.setenv("CASPER_CLAUDE_CLI", "/nonexistent/missing-claude")
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "hang")
    monkeypatch.setenv("CASPER_FAKE_SLEEP", "3.0")

    report = llm.status(timeout=0.4)
    assert report.backends["rules"].available is True
    assert report.backends["claude"].available is False
    assert report.backends["claude"].executable is None
    assert report.backends["agy"].available is False
    assert report.backends["agy"].reason is not None
    assert "timed out" in report.backends["agy"].reason.lower()


def test_tc042_status_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """TC-042: llm.status() marks CLI unavailable on nonzero --version exit."""
    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_FAKE_MODE", "fail")

    report = llm.status(timeout=5.0)
    assert report.backends["claude"].available is False
    assert report.backends["agy"].available is False
    assert report.backends["claude"].reason


def test_build_prompt_safe_voice_provenance_and_constraints() -> None:
    libs, _, adapted, _ = _make_plan()
    realizer = llm.CliAgentRealizer(BackendKind.CLAUDE, libs)
    voice: dict[str, Any] = {
        "_provenance": {
            "style_guide.local_rule": "local",
            "sentences.passive_rate": "local",
            "exemplars.short_lines": "local",
            "pins.local_pin": "local",
        },
        "style_guide": [
            "not-a-dict",
            {"id": "empty_rule", "rule": "   "},
            {"id": "local_rule", "area": "private", "rule": "Private local rule."},
            {"id": "clarity_rule", "area": "clarity", "rule": "Use active voice."},
        ],
        "sentences": {
            "length_words": {"mean": 12.3456},
            "short_rate_le8": 0.25,
            "long_rate_ge30": 0.05,
            "passive_rate": 0.1,
            "question_rate": 0.05,
        },
        "lexical": {
            "flesch_kincaid_grade": 8.4,
            "mean_word_length": 4.6,
        },
        "voice": {
            "contractions_per_1k": 5.0,
            "person_per_1k": {"first_plural_inclusive": 3.0, "second": 1.0},
            "punctuation_per_1k": {"em_dash": 0.5, "semicolon": 0.2},
        },
        "headings": {
            "case_style": "sentence",
            "density_per_1k": 2.0,
        },
        "exemplars": {
            "openers": ["Here is the update.", "  "],
            "closers": ["Let me know if blocked."],
            "short_lines": ["Shipped."],
        },
        "pins": {
            "mean_words": {"value": 14.25},
            "local_pin": {"value": 99.0},
            "author": {"value": 1.0},
        },
    }
    constraints = Constraints(max_words=100, max_chars=500, banned=("forbiddenword",))
    prompt = realizer.build_prompt(adapted, voice, constraints, provenance=None)

    assert "LIMITS: max_words=100, max_chars=500" in prompt
    assert "forbiddenword" in prompt
    assert "- clarity: Use active voice." in prompt
    assert "Private local rule." not in prompt
    assert "mean_sentence_words=12.346" in prompt
    assert "passive_rate" not in prompt
    assert "flesch_kincaid_grade=8.4" in prompt
    assert "contractions_per_1k=5.0" in prompt
    assert "heading_case_style=sentence" in prompt
    assert "- exemplar_openers: Here is the update." in prompt
    assert "- exemplar_closers: Let me know if blocked." in prompt
    assert "exemplar_short_lines" not in prompt
    assert "- pinned_targets: mean_words=14.25" in prompt
    assert "local_pin" not in prompt

    voice_no_local = dict(voice, _provenance={})
    prompt_all_exemplars = realizer.build_prompt(adapted, voice_no_local, constraints)
    assert "- exemplar_short_lines: Shipped." in prompt_all_exemplars


def test_realize_empty_plan_skips_runner() -> None:
    libs, _, adapted, modality = _make_plan()
    empty_plan = dataclasses.replace(
        adapted,
        sections=tuple(dataclasses.replace(ps, facts=()) for ps in adapted.sections),
    )

    def fail_runner(*args: Any) -> tuple[int, str, str]:
        raise AssertionError("runner must not be called for empty plan")

    realizer = llm.CliAgentRealizer(BackendKind.CLAUDE, libs, runner=fail_runner)
    draft = realizer.realize(empty_plan, None, Constraints(), modality)
    assert draft.sections == ()
    assert draft.backend == BackendKind.CLAUDE


def test_realize_parses_headings_bullets_multicite_trailing_punct_and_cta() -> None:
    libs, _, adapted, modality = _make_plan()
    assert adapted.cta_style is not None

    def runner(*args: Any) -> tuple[int, str, str]:
        return (
            0,
            "\n".join(
                [
                    "## status",
                    "Status is green. [f001] Metrics improved. [f002]",
                    "## Risks & Blockers",
                    "- Legacy cache invalidation remains a minor risk [f003].",
                    "## next-steps",
                    "1. Production cutover is scheduled for Friday [f004].",
                ]
            ),
            "",
        )

    realizer = llm.CliAgentRealizer(BackendKind.CLAUDE, libs, runner=runner)
    draft = realizer.realize(adapted, None, Constraints(seed=0), modality)

    by_name = {sec.name: sec for sec in draft.sections}
    assert len(by_name["status"].sentences) == 2
    assert by_name["status"].sentences[0].fact_ids == ("f001",)
    assert by_name["status"].sentences[1].fact_ids == ("f002",)
    assert by_name["risks"].sentences[0].text == "Legacy cache invalidation remains a minor risk."
    assert by_name["risks"].sentences[0].fact_ids == ("f003",)
    assert by_name["next_steps"].sentences[0].text == "Production cutover is scheduled for Friday."
    assert by_name["next_steps"].sentences[0].fact_ids == ("f004",)
    assert draft.sections[-1].sentences[-1].frame is True
    assert draft.sections[-1].sentences[-1].fact_ids == ()


def test_realize_headings_only_nonzero_stdout_and_env_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    libs, _, adapted, modality = _make_plan()

    headings_only = llm.CliAgentRealizer(
        BackendKind.CLAUDE,
        libs,
        runner=lambda *args: (0, "## status\n   \n## risks\n", ""),
    )
    with pytest.raises(BackendError, match="no parseable sentences"):
        headings_only.realize(adapted, None, Constraints(), modality)

    rc1_stdout = llm.CliAgentRealizer(
        BackendKind.CLAUDE,
        libs,
        runner=lambda *args: (1, "stdout error detail", ""),
    )
    with pytest.raises(BackendError, match="stdout error detail"):
        rc1_stdout.realize(adapted, None, Constraints(), modality)

    monkeypatch.setenv("CASPER_CLAUDE_MODEL", "claude-env-model")
    captured_argv: list[str] = []

    def env_model_runner(argv: Any, cwd: Path, timeout: float, env: Any) -> tuple[int, str, str]:
        captured_argv.extend(argv)
        first_fact = adapted.sections[0].facts[0]
        return (0, f"## {adapted.sections[0].section.name}\n{first_fact.text} [{first_fact.id}]\n", "")

    env_realizer = llm.CliAgentRealizer(BackendKind.CLAUDE, libs, model=None, runner=env_model_runner)
    draft = env_realizer.realize(adapted, None, Constraints(), modality)
    assert "--model" in captured_argv
    assert captured_argv[captured_argv.index("--model") + 1] == "claude-env-model"
    assert draft.meta["model"] == "claude-env-model"


def test_status_injected_runner_empty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASPER_CLAUDE_CLI", str(FAKE_AGENT))
    monkeypatch.setenv("CASPER_AGY_CLI", str(FAKE_AGENT))
    report = llm.status(runner=lambda *args: (0, "", ""))
    assert report.backends["claude"].available is False
    assert report.backends["agy"].available is False
