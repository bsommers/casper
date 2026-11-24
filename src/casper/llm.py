"""Optional external CLI writers (`claude` and `agy`) behind strict privacy & isolation (Rank 5, ADR 0010)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from casper.errors import BackendError, InputError
from casper.models import (
    AdaptedPlan,
    BackendAvailability,
    BackendKind,
    BackendStatusReport,
    Constraints,
    Draft,
    DraftSection,
    Libraries,
    Modality,
    Sentence,
)
from casper.realizer import fit_to_limits, substitute

CommandRunner = Callable[
    [Sequence[str], Path, float, Mapping[str, str]],
    tuple[int, str, str],
]

CITATION_RE = re.compile(r"\[(f\d{3,}(?:\s*,\s*f\d{3,})*)\]([.!?])?\s*$")
_MULTI_CITE_SPLIT_RE = re.compile(r"(?<=\])(?:[.!?])?\s+(?=[A-Z0-9\"'(])")
_BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*$")
_TOKEN_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)*")

_COMMON_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NO_COLOR",
)

_BACKEND_ENV_CONFIG: dict[BackendKind, tuple[str, str, str, tuple[str, ...]]] = {
    BackendKind.CLAUDE: (
        "claude",
        "CASPER_CLAUDE_CLI",
        "CASPER_CLAUDE_MODEL",
        ("ANTHROPIC_API_KEY",),
    ),
    BackendKind.AGY: (
        "agy",
        "CASPER_AGY_CLI",
        "CASPER_AGY_MODEL",
        ("GEMINI_API_KEY",),
    ),
}

_FORBIDDEN_VOICE_KEYS: frozenset[str] = frozenset(
    {"author", "sources", "generated", "overlays", "email", "consent", "_provenance"}
)


def _package_version() -> str:
    try:
        return importlib.metadata.version("casper")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _minimal_env(backend: BackendKind) -> dict[str, str]:
    """Construct a minimal, privacy-safe environment allowlist for CLI subprocesses."""
    allowed = set(_COMMON_ENV_ALLOWLIST)
    if backend in _BACKEND_ENV_CONFIG:
        allowed.update(_BACKEND_ENV_CONFIG[backend][3])
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in allowed or key.startswith("CASPER_FAKE_"):
            env[key] = value
    return env


def _resolve_executable(backend: BackendKind) -> str | None:
    """Resolve CLI executable from override env var or PATH."""
    default_cmd, cli_env, _, _ = _BACKEND_ENV_CONFIG[backend]
    override = os.environ.get(cli_env, "").strip()
    if override:
        found = shutil.which(override)
        if found:
            return found
        candidate = Path(override)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which(default_cmd)


def _resolve_model(backend: BackendKind, explicit_model: str | None) -> str | None:
    if explicit_model is not None and explicit_model.strip():
        return explicit_model.strip()
    _, _, model_env, _ = _BACKEND_ENV_CONFIG[backend]
    env_model = os.environ.get(model_env, "").strip()
    return env_model or None


def _default_runner(
    argv: Sequence[str],
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
) -> tuple[int, str, str]:
    """Execute external CLI safely: shell=False, fresh temp cwd, stdin=DEVNULL, hard timeout."""
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(env),
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"CLI command timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise BackendError(f"Failed to execute CLI command: {exc}") from exc
    return completed.returncode, completed.stdout, completed.stderr


def _is_local_path(dotted_path: str, provenance: Mapping[str, str]) -> bool:
    """Return True if dotted_path or any ancestor prefix originates from a local layer."""
    if not provenance:
        return False
    parts = dotted_path.split(".")
    for idx in range(1, len(parts) + 1):
        prefix = ".".join(parts[:idx])
        source = provenance.get(prefix)
        if source is not None and str(source).startswith("local"):
            return True
    return False


def _get_nested(mapping: Mapping[str, Any], path: str) -> Any:
    cur: Any = mapping
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part in _FORBIDDEN_VOICE_KEYS:
            return None
        cur = cur.get(part)
    return cur


def _extract_safe_voice(
    voice: Mapping[str, Any] | None,
    provenance: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Allowlist-extract style guidance from a voice profile, excluding all private/local data."""
    if not voice:
        return {}

    prov: Mapping[str, str] = provenance if provenance is not None else {}
    if not prov and isinstance(voice.get("_provenance"), Mapping):
        prov = {str(k): str(v) for k, v in voice["_provenance"].items()}

    safe: dict[str, Any] = {}

    # 1. Style guide rules (exclude any local-provenance rule).
    raw_guide = voice.get("style_guide")
    if isinstance(raw_guide, list) and not _is_local_path("style_guide", prov):
        kept_rules: list[str] = []
        for entry in raw_guide:
            if not isinstance(entry, Mapping):
                continue
            rule_id = str(entry.get("id", "")).strip()
            rule_text = str(entry.get("rule", "")).strip()
            if not rule_text:
                continue
            if rule_id and _is_local_path(f"style_guide.{rule_id}", prov):
                continue
            area = str(entry.get("area", rule_id or "style")).strip()
            kept_rules.append(f"{area}: {rule_text}")
        if kept_rules:
            safe["style_guide"] = kept_rules

    # 2. Safe scalar numeric voice metrics (strict path allowlist).
    metric_paths: tuple[tuple[str, str], ...] = (
        ("mean_sentence_words", "sentences.length_words.mean"),
        ("short_sentence_rate", "sentences.short_rate_le8"),
        ("long_sentence_rate", "sentences.long_rate_ge30"),
        ("passive_rate", "sentences.passive_rate"),
        ("question_rate", "sentences.question_rate"),
        ("flesch_kincaid_grade", "lexical.flesch_kincaid_grade"),
        ("mean_word_length", "lexical.mean_word_length"),
        ("contractions_per_1k", "voice.contractions_per_1k"),
        ("first_plural_per_1k", "voice.person_per_1k.first_plural_inclusive"),
        ("second_person_per_1k", "voice.person_per_1k.second"),
        ("em_dash_per_1k", "voice.punctuation_per_1k.em_dash"),
        ("semicolon_per_1k", "voice.punctuation_per_1k.semicolon"),
        ("heading_case_style", "headings.case_style"),
        ("heading_density_per_1k", "headings.density_per_1k"),
    )
    metrics: dict[str, Any] = {}
    for label, path in metric_paths:
        if _is_local_path(path, prov):
            continue
        val = _get_nested(voice, path)
        if isinstance(val, (int, float, str)) and not isinstance(val, bool):
            metrics[label] = round(val, 3) if isinstance(val, float) else val
    if metrics:
        safe["metrics"] = metrics

    # 3. Safe exemplars (excluding any local-provenance lists).
    exemplars_out: dict[str, list[str]] = {}
    for bucket in ("openers", "closers", "short_lines"):
        path = f"exemplars.{bucket}"
        if _is_local_path(path, prov):
            continue
        vals = _get_nested(voice, path)
        if isinstance(vals, list):
            cleaned = [str(v).strip() for v in vals if isinstance(v, str) and v.strip()]
            if cleaned:
                exemplars_out[bucket] = cleaned[:4]
    if exemplars_out:
        safe["exemplars"] = exemplars_out

    # 4. Safe non-local pins.
    raw_pins = voice.get("pins")
    if isinstance(raw_pins, Mapping) and not _is_local_path("pins", prov):
        pins_out: dict[str, float] = {}
        for key, spec in sorted(raw_pins.items()):
            key_s = str(key)
            if key_s in _FORBIDDEN_VOICE_KEYS or _is_local_path(f"pins.{key_s}", prov):
                continue
            if isinstance(spec, Mapping) and isinstance(spec.get("value"), (int, float)):
                if not _is_local_path(f"pins.{key_s}.value", prov):
                    pins_out[key_s] = round(float(spec["value"]), 3)
        if pins_out:
            safe["pins"] = pins_out

    return safe


def _strip_outer_code_fences(raw_text: str) -> str:
    lines = raw_text.strip().splitlines()
    if len(lines) >= 2 and _CODE_FENCE_RE.match(lines[0]) and _CODE_FENCE_RE.match(lines[-1]):
        return "\n".join(lines[1:-1]).strip()
    return raw_text.strip()


def _extract_substitution_tokens(substitutions: Mapping[str, str]) -> frozenset[str]:
    tokens: set[str] = set()
    for replacement in substitutions.values():
        for tok in _TOKEN_RE.findall(replacement):
            tokens.add(tok.lower())
    return frozenset(tokens)


class CliAgentRealizer:
    """Optional external CLI realizer supporting `claude` and `agy` backends (ADR 0010)."""

    def __init__(
        self,
        backend: BackendKind,
        libs: Libraries,
        *,
        timeout: int = 90,
        model: str | None = None,
        runner: CommandRunner | None = None,
    ) -> None:
        if backend not in (BackendKind.CLAUDE, BackendKind.AGY):
            raise InputError(
                f"CliAgentRealizer requires backend 'claude' or 'agy', got {backend!r}"
            )
        if timeout <= 0:
            raise InputError(f"CLI timeout must be positive, got {timeout}")
        self.backend = backend
        self.libs = libs
        self.timeout = int(timeout)
        self.model = model
        self._runner = runner

    def build_prompt(
        self,
        adapted_plan: AdaptedPlan,
        voice: dict[str, Any] | None,
        constraints: Constraints,
        *,
        provenance: Mapping[str, str] | None = None,
    ) -> str:
        """Build a privacy-safe, strictly grounded prompt for `claude` or `agy`."""
        lines: list[str] = [
            "You are drafting a factual document from verified source facts.",
            "STRICT RULES:",
            "1. Use ONLY the facts listed below. Never invent numbers, percentages, currencies, dates, or proper names.",
            "2. Preserve exact polarity (do not negate affirmative facts or affirm negated facts).",
            "3. Every sentence MUST end with valid fact citations in square brackets, e.g. [f001] or [f001, f002].",
            "4. Output ONLY markdown sections using exact `## <section_name>` headers matching the plan below.",
            "5. Do not include code fences, preamble, explanations, or a closing CTA line.",
            "",
            f"STRUCTURE: {adapted_plan.structure.id} — {adapted_plan.structure.goal}",
            f"SOURCE PERSONA: {adapted_plan.source.id} (depth={adapted_plan.source.detail_depth}, jargon={adapted_plan.source.jargon_level})",
            f"TARGET PERSONA: {adapted_plan.target.id} (depth={adapted_plan.target.detail_depth}, jargon={adapted_plan.target.jargon_level})",
        ]

        if adapted_plan.target.vocabulary_avoid:
            avoid = ", ".join(adapted_plan.target.vocabulary_avoid)
            lines.append(f"AVOID TERMS: {avoid}")

        banned_terms = tuple(dict.fromkeys((*self.libs.glossary.banned, *constraints.banned)))
        if banned_terms:
            lines.append(f"BANNED TERMS: {', '.join(banned_terms)}")

        if adapted_plan.substitutions:
            subs = "; ".join(
                f"{k} -> {v}" for k, v in sorted(adapted_plan.substitutions.items())
            )
            lines.append(f"PREFERRED TERMINOLOGY: {subs}")

        limit_parts: list[str] = []
        if constraints.max_words is not None:
            limit_parts.append(f"max_words={constraints.max_words}")
        if constraints.max_chars is not None:
            limit_parts.append(f"max_chars={constraints.max_chars}")
        if limit_parts:
            lines.append(f"LIMITS: {', '.join(limit_parts)}")

        safe_voice = _extract_safe_voice(voice, provenance)
        if safe_voice:
            lines.append("")
            lines.append("VOICE STYLE GUIDANCE (ANONYMIZED):")
            if "style_guide" in safe_voice:
                for rule in safe_voice["style_guide"]:
                    lines.append(f"- {rule}")
            if "metrics" in safe_voice:
                metric_str = ", ".join(
                    f"{k}={v}" for k, v in sorted(safe_voice["metrics"].items())
                )
                lines.append(f"- target_metrics: {metric_str}")
            if "pins" in safe_voice:
                pin_str = ", ".join(f"{k}={v}" for k, v in sorted(safe_voice["pins"].items()))
                lines.append(f"- pinned_targets: {pin_str}")
            if "exemplars" in safe_voice:
                for bucket, items in sorted(safe_voice["exemplars"].items()):
                    lines.append(f"- exemplar_{bucket}: {' | '.join(items)}")

        lines.append("")
        lines.append("PLANNED SECTIONS AND FACTS:")
        for ps in adapted_plan.sections:
            if not ps.facts:
                continue
            lines.append(f"## {ps.section.name}")
            lines.append(f"Heading: {ps.section.heading}")
            lines.append(f"Purpose: {ps.section.purpose}")
            for fact in ps.facts:
                prepared = substitute(fact.text, adapted_plan.substitutions)
                lines.append(f"- [{fact.id}] ({fact.kind}) {prepared}")

        lines.append("")
        lines.append("Write the draft now using `## <section_name>` headings and `[fNNN]` citations:")
        return "\n".join(lines) + "\n"

    def _select_closing_phrase(
        self,
        adapted_plan: AdaptedPlan,
        constraints: Constraints,
    ) -> str | None:
        if adapted_plan.cta_style is None:
            return None
        phrases = self.libs.phrasebank.get(adapted_plan.cta_style)
        if not phrases:
            return None
        return phrases[constraints.seed % len(phrases)]

    def _parse_response(
        self,
        raw_text: str,
        adapted_plan: AdaptedPlan,
        constraints: Constraints,
    ) -> tuple[list[DraftSection], frozenset[str]]:
        cleaned = _strip_outer_code_fences(raw_text)
        if not cleaned:
            return [], frozenset()

        non_empty_planned = [ps for ps in adapted_plan.sections if ps.facts]
        if not non_empty_planned:
            return [], frozenset()

        section_lookup: dict[str, tuple[str, str]] = {}
        ordered_sections: list[tuple[str, str]] = []
        for ps in non_empty_planned:
            pair = (ps.section.name, ps.section.heading)
            ordered_sections.append(pair)
            section_lookup[ps.section.name.strip().lower()] = pair
            if ps.section.heading.strip():
                section_lookup[ps.section.heading.strip().lower()] = pair

        buckets: dict[str, list[Sentence]] = {name: [] for name, _ in ordered_sections}
        current_name = ordered_sections[0][0]
        extra_headings: dict[str, str] = {name: heading for name, heading in ordered_sections}

        for raw_line in cleaned.splitlines():
            stripped = raw_line.strip()
            if not stripped or _CODE_FENCE_RE.match(stripped):
                continue

            heading_match = _HEADING_RE.match(stripped)
            if heading_match:
                h_text = heading_match.group(1).strip()
                h_key = h_text.lower()
                matched = section_lookup.get(h_key)
                if matched is not None:
                    current_name = matched[0]
                else:
                    # Match by normalized name/heading (underscores vs spaces).
                    norm_key = re.sub(r"[\s_-]+", "_", h_key).strip("_")
                    matched_norm = next(
                        (
                            pair
                            for pair in ordered_sections
                            if re.sub(r"[\s_-]+", "_", pair[0].lower()) == norm_key
                            or re.sub(r"[\s_-]+", "_", pair[1].lower()) == norm_key
                        ),
                        None,
                    )
                    if matched_norm is not None:
                        current_name = matched_norm[0]
                continue

            line_body = _BULLET_PREFIX_RE.sub("", stripped).strip()
            if not line_body:
                continue

            # Split multi-sentence lines when each sentence carries its own trailing [fNNN].
            segments = _MULTI_CITE_SPLIT_RE.split(line_body)
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue
                cite_match = CITATION_RE.search(seg)
                if cite_match:
                    fact_ids = tuple(
                        fid.strip() for fid in cite_match.group(1).split(",") if fid.strip()
                    )
                    trailing_punct = cite_match.group(2) or ""
                    body = CITATION_RE.sub("", seg).strip()
                    if trailing_punct and body and body[-1] not in ".!?":
                        body = f"{body}{trailing_punct}"
                else:
                    fact_ids = ()
                    body = seg

                body = substitute(body, adapted_plan.substitutions).strip()
                if not body:
                    continue
                buckets[current_name].append(Sentence(text=body, fact_ids=fact_ids, frame=False))

        draft_sections: list[DraftSection] = []
        for name, _ in ordered_sections:
            sents = buckets[name]
            if sents:
                draft_sections.append(
                    DraftSection(
                        name=name,
                        heading=extra_headings[name],
                        sentences=tuple(sents),
                    )
                )

        closing_phrase = self._select_closing_phrase(adapted_plan, constraints)
        if draft_sections and closing_phrase is not None:
            last = draft_sections[-1]
            draft_sections[-1] = DraftSection(
                name=last.name,
                heading=last.heading,
                sentences=(*last.sentences, Sentence(text=closing_phrase, fact_ids=(), frame=True)),
            )

        declared = _extract_substitution_tokens(adapted_plan.substitutions)
        return draft_sections, declared

    def realize(
        self,
        adapted_plan: AdaptedPlan,
        voice: dict[str, Any] | None,
        constraints: Constraints,
        modality: Modality,
        *,
        nlp: Any | None = None,
        provenance: Mapping[str, str] | None = None,
    ) -> Draft:
        """Invoke the configured CLI backend in isolation and parse its cited draft."""
        del nlp  # External CLI performs realization; validation runs separately in validator.py.
        non_empty_sections = [ps for ps in adapted_plan.sections if ps.facts]
        if not non_empty_sections:
            empty_draft = Draft(
                sections=(),
                warnings=adapted_plan.warnings,
                candidates_considered=1,
                backend=self.backend,
                declared_additions=frozenset(),
            )
            return fit_to_limits(empty_draft, adapted_plan, constraints, modality)

        exe = _resolve_executable(self.backend)
        if exe is None:
            if self._runner is None:
                raise BackendError(
                    f"{self.backend} CLI executable not found on PATH or override environment variable."
                )
            exe = str(self.backend)

        resolved_model = _resolve_model(self.backend, self.model)
        prompt = self.build_prompt(adapted_plan, voice, constraints, provenance=provenance)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        if self.backend == BackendKind.AGY:
            argv = [exe, "--output-format", "text"]
            if resolved_model:
                argv.extend(["--model", resolved_model])
            argv.extend(["-p", prompt])
        else:
            argv = [exe, "-p", "--output-format", "text"]
            if resolved_model:
                argv.extend(["--model", resolved_model])
            argv.append(prompt)

        runner = self._runner if self._runner is not None else _default_runner
        env = _minimal_env(self.backend)

        with tempfile.TemporaryDirectory(prefix="casper-cli-") as tmpdir:
            rc, stdout, stderr = runner(argv, Path(tmpdir), float(self.timeout), env)

        if rc != 0:
            err_detail = stderr.strip() or stdout.strip() or f"exit status {rc}"
            raise BackendError(f"{self.backend} CLI failed (exit {rc}): {err_detail}")

        if not stdout or not stdout.strip():
            raise BackendError(f"{self.backend} CLI returned empty output.")

        response_sha256 = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        draft_sections, declared = self._parse_response(stdout, adapted_plan, constraints)
        if not draft_sections:
            raise BackendError(f"{self.backend} CLI produced no parseable sentences.")

        draft = Draft(
            sections=tuple(draft_sections),
            warnings=adapted_plan.warnings,
            candidates_considered=1,
            backend=self.backend,
            declared_additions=declared,
            meta={
                "backend": str(self.backend),
                "model": resolved_model,
                "prompt_sha256": prompt_sha256,
                "response_sha256": response_sha256,
            },
        )
        return fit_to_limits(draft, adapted_plan, constraints, modality)


def status(
    *,
    timeout: float = 20.0,
    runner: CommandRunner | None = None,
) -> BackendStatusReport:
    """Probe availability and version of `rules`, `claude`, and `agy` backends."""
    backends: dict[str, BackendAvailability] = {
        str(BackendKind.RULES): BackendAvailability(
            backend=BackendKind.RULES,
            available=True,
            executable="builtin",
            version=_package_version(),
            reason=None,
        )
    }

    active_runner = runner if runner is not None else _default_runner

    for backend in (BackendKind.CLAUDE, BackendKind.AGY):
        exe = _resolve_executable(backend)
        if exe is None:
            backends[str(backend)] = BackendAvailability(
                backend=backend,
                available=False,
                executable=None,
                version=None,
                reason=f"{backend} executable not found",
            )
            continue

        env = _minimal_env(backend)
        try:
            with tempfile.TemporaryDirectory(prefix="casper-status-") as tmpdir:
                rc, stdout, stderr = active_runner(
                    [exe, "--version"],
                    Path(tmpdir),
                    float(timeout),
                    env,
                )
        except BackendError as exc:
            backends[str(backend)] = BackendAvailability(
                backend=backend,
                available=False,
                executable=exe,
                version=None,
                reason=exc.message,
            )
            continue

        version_line = (stdout.strip().splitlines()[0].strip()) if stdout.strip() else ""
        if rc == 0 and version_line:
            backends[str(backend)] = BackendAvailability(
                backend=backend,
                available=True,
                executable=exe,
                version=version_line,
                reason=None,
            )
        else:
            err_msg = stderr.strip() or stdout.strip() or f"exit status {rc}"
            backends[str(backend)] = BackendAvailability(
                backend=backend,
                available=False,
                executable=exe,
                version=None,
                reason=err_msg,
            )

    return BackendStatusReport(backends=backends)
