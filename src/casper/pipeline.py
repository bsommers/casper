"""End-to-end deterministic/assisted generation pipeline and reproducibility record (Rank 6)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

from casper import facts as facts_mod
from casper import planner, validator
from casper.catalog import find_profile
from casper.errors import BackendError, InputError
from casper.layers import load_resolved_profile
from casper.libraries import check_combo, load_libraries
from casper.llm import CliAgentRealizer, CommandRunner
from casper.modalities import format_draft
from casper.models import (
    BackendKind,
    BackendRecord,
    Brief,
    Constraints,
    Draft,
    FactTraceEntry,
    FidelityMode,
    Libraries,
    PersonaKind,
    ReproducibilityRecord,
    Result,
)
from casper.parsing import load_nlp
from casper.realizer import RuleBasedRealizer, fit_to_limits


def _package_version() -> str:
    try:
        return importlib.metadata.version("casper")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _coerce_backend(value: BackendKind | str) -> BackendKind:
    if isinstance(value, BackendKind):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        try:
            return BackendKind(normalized)
        except ValueError:
            pass
    valid = ", ".join(str(b) for b in BackendKind)
    raise InputError(f"Unknown backend {value!r}; valid choices: {valid}")


def _build_fact_trace(draft: Draft, fact_by_id: dict[str, Any]) -> tuple[FactTraceEntry, ...]:
    entries: list[FactTraceEntry] = []
    for section in draft.sections:
        for sent in section.sentences:
            cited: list[dict[str, str]] = []
            for fid in sent.fact_ids:
                fact = fact_by_id.get(fid)
                if fact is not None:
                    cited.append(
                        {
                            "id": fact.id,
                            "kind": str(fact.kind),
                            "source": fact.source,
                            "text": fact.text,
                        }
                    )
            entries.append(
                FactTraceEntry(
                    section=section.name,
                    text=sent.text,
                    frame=sent.frame,
                    facts=tuple(cited),
                )
            )
    return tuple(entries)


def _compute_record_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def generate(
    brief: Brief,
    *,
    libs: Libraries | None = None,
    nlp: Any | None = None,
    runner: CommandRunner | None = None,
    allow_author_path: bool = True,
) -> Result:
    """Execute the full Casper generation pipeline and return a complete Result.

    Never raises on draft validation errors; validation findings live in `Result.validation`.
    """
    requested_backend = _coerce_backend(brief.backend)
    active_libs = (
        libs
        if libs is not None
        else load_libraries(Path(brief.project_dir) if brief.project_dir else None)
    )
    check_combo(active_libs, brief.structure, brief.modality, brief.target, brief.source)

    voice: dict[str, Any] | None = None
    provenance: dict[str, str] = {}
    author_corpus_sha256: str | None = None
    if brief.author:
        profile_path = find_profile(
            brief.author,
            Path(brief.authors_dir),
            allow_path=allow_author_path,
        )
        voice, provenance = load_resolved_profile(profile_path, overlays=(brief.modality,))
        generated_meta = voice.get("generated")
        if isinstance(generated_meta, dict):
            raw_corpus_sha = generated_meta.get("corpus_sha256")
            if isinstance(raw_corpus_sha, str) and raw_corpus_sha:
                author_corpus_sha256 = raw_corpus_sha

    nlp_ner = nlp if nlp is not None else load_nlp(ner=True)
    nlp_no_ner = nlp if nlp is not None else load_nlp(ner=False)

    fact_model = facts_mod.ingest(
        inputs=brief.inputs,
        notes=brief.notes,
        nlp=nlp_ner,
        fact_overrides=brief.fact_overrides or None,
    )

    structure = active_libs.structures[brief.structure]
    modality = active_libs.modalities[brief.modality]
    source = active_libs.personas[(PersonaKind.SOURCE, brief.source)]
    target = active_libs.personas[(PersonaKind.TARGET, brief.target)]

    plan = planner.plan_structure(fact_model, structure)
    adapted = planner.adapt(plan, source, target, active_libs.glossary)

    constraints = Constraints(
        max_words=modality.max_words,
        max_chars=modality.max_chars,
        banned=tuple(brief.banned),
        candidates=brief.candidates,
        seed=brief.seed,
        min_voice=brief.min_voice,
    )

    used_backend = requested_backend
    extra_warnings: list[str] = []

    if requested_backend == BackendKind.RULES:
        draft = RuleBasedRealizer(active_libs).realize(
            adapted,
            voice,
            constraints,
            modality,
            nlp=nlp_no_ner,
        )
    else:
        cli_realizer = CliAgentRealizer(
            requested_backend,
            active_libs,
            timeout=brief.timeout,
            model=brief.model,
            runner=runner,
        )
        try:
            draft = cli_realizer.realize(
                adapted,
                voice,
                constraints,
                modality,
                nlp=nlp_no_ner,
                provenance=provenance,
            )
        except BackendError as exc:
            if not brief.fallback:
                raise
            used_backend = BackendKind.RULES
            extra_warnings.append(
                f"Backend '{requested_backend}' failed ({exc.message}); fell back to 'rules'."
            )
            draft = RuleBasedRealizer(active_libs).realize(
                adapted,
                voice,
                constraints,
                modality,
                nlp=nlp_no_ner,
            )

    # Populate title when modality expects one.
    resolved_title = draft.title
    if modality.title and not resolved_title:
        if brief.topic and brief.topic.strip():
            resolved_title = brief.topic.strip()
        else:
            resolved_title = structure.id.replace("_", " ").title()

    combined_warnings = tuple(
        dict.fromkeys((*fact_model.warnings, *draft.warnings, *extra_warnings))
    )
    if resolved_title != draft.title or combined_warnings != draft.warnings:
        draft = Draft(
            sections=draft.sections,
            title=resolved_title,
            warnings=combined_warnings,
            candidates_considered=draft.candidates_considered,
            backend=draft.backend,
            declared_additions=draft.declared_additions,
            meta=dict(draft.meta),
        )
        draft = fit_to_limits(draft, adapted, constraints, modality)

    fidelity_mode = (
        FidelityMode.STRICT if used_backend == BackendKind.RULES else FidelityMode.ASSISTED
    )
    validation = validator.validate(
        draft,
        adapted,
        fact_model,
        voice,
        constraints,
        modality,
        fidelity_mode=fidelity_mode,
        glossary=active_libs.glossary,
        nlp=nlp_no_ner,
    )

    text = format_draft(draft, modality)
    fact_by_id = {f.id: f for f in fact_model.facts}
    fact_trace = _build_fact_trace(draft, fact_by_id)

    backend_record = BackendRecord(
        requested=requested_backend,
        used=used_backend,
        deterministic=(used_backend == BackendKind.RULES),
        model=draft.meta.get("model") if used_backend != BackendKind.RULES else None,
        prompt_sha256=(
            draft.meta.get("prompt_sha256") if used_backend != BackendKind.RULES else None
        ),
        response_sha256=(
            draft.meta.get("response_sha256") if used_backend != BackendKind.RULES else None
        ),
    )

    selectors: dict[str, str | None] = {
        "structure": brief.structure,
        "modality": brief.modality,
        "source": brief.source,
        "target": brief.target,
        "author": brief.author,
    }
    output_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    tool_version = _package_version()

    record_body: dict[str, Any] = {
        "tool_version": tool_version,
        "seed": brief.seed,
        "candidates": brief.candidates,
        "selectors": selectors,
        "input_hashes": dict(sorted(fact_model.input_hashes.items())),
        "facts_digest": fact_model.digest,
        "config_digest": active_libs.digest,
        "author_corpus_sha256": author_corpus_sha256,
        "output_sha256": output_sha256,
        "backend": backend_record.to_dict(),
    }
    record_sha256 = _compute_record_sha256(record_body)

    record = ReproducibilityRecord(
        tool_version=tool_version,
        seed=brief.seed,
        candidates=brief.candidates,
        selectors=selectors,
        input_hashes=dict(sorted(fact_model.input_hashes.items())),
        facts_digest=fact_model.digest,
        config_digest=active_libs.digest,
        author_corpus_sha256=author_corpus_sha256,
        output_sha256=output_sha256,
        backend=backend_record,
        record_sha256=record_sha256,
    )

    return Result(
        text=text,
        draft=draft,
        validation=validation,
        fact_trace=fact_trace,
        record=record,
        facts=fact_model.facts,
    )
