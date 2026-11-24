"""Uniform core command dispatcher owning all 10 typed domain operations (Rank 7).

Python public API (`casper.*`), CLI (`cli.py`), and HTTP API (`web/server.py`)
route exclusively through these 10 functions. This module MUST NEVER import `cli` or `web`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from casper import conformance, facts, llm, pipeline
from casper.catalog import AUTHOR_ID_RE, diff_authors, find_profile, list_authors
from casper.errors import InputError, ProfileError, SecurityError
from casper.layers import drift_report, load_resolved_profile, write_local_email
from casper.libraries import load_libraries
from casper.llm import CommandRunner
from casper.loaders import load_bytes, load_document
from casper.models import (
    AuthorDiff,
    AuthorSummary,
    BackendKind,
    BackendStatusReport,
    Brief,
    ConformanceReport,
    FactKind,
    FactModel,
    PersonaKind,
    Result,
)
from casper.profile import build_profile, check_profile_writable, load_profile, save_profile


def _load_optional_layer(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"Failed to parse layer YAML {path.name}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ProfileError(f"Profile layer {path.name} must be a YAML mapping")
    return loaded


def write_draft(
    brief: Brief,
    *,
    allow_author_path: bool = True,
    runner: CommandRunner | None = None,
) -> Result:
    """Generate a fact-grounded, validated draft from a Brief."""
    return pipeline.generate(
        brief,
        runner=runner,
        allow_author_path=allow_author_path,
    )


def extract_facts(
    inputs: Sequence[str | Path] = (),
    notes: str | None = None,
    *,
    fact_overrides: Mapping[str, FactKind] | None = None,
) -> FactModel:
    """Extract and classify structured facts from files and/or inline notes."""
    return facts.ingest(
        inputs=inputs,
        notes=notes,
        fact_overrides=fact_overrides,
    )


def score_draft(
    author_ref: str,
    text_or_path: str | Path,
    *,
    authors_dir: Path = Path("authors"),
    is_text: bool = False,
    raw: bool = False,
    overlay: str | None = None,
    allow_author_path: bool = True,
) -> ConformanceReport:
    """Score a draft file or raw text against an author's voice profile."""
    if raw and overlay:
        raise InputError("Cannot combine --raw with --overlay")

    profile_path = find_profile(
        author_ref,
        Path(authors_dir),
        allow_path=allow_author_path,
    )
    if raw:
        profile = load_profile(profile_path)
    else:
        overlays = (overlay,) if overlay else ()
        profile, _ = load_resolved_profile(profile_path, overlays=overlays)

    if is_text:
        raw_text = str(text_or_path)
        if not raw_text.strip():
            raise InputError("Candidate text has no scorable prose")
        doc = load_bytes(raw_text.encode("utf-8"), "<inline>")
    else:
        doc = load_document(text_or_path)

    return conformance.score(profile, doc)


def list_options(
    *,
    project_dir: Path | None = None,
    authors_dir: Path = Path("authors"),
) -> dict[str, Any]:
    """Return available personas, structures, modalities, authors, and backends."""
    libs = load_libraries(project_dir)
    source_personas = sorted(
        (p for p in libs.personas.values() if p.kind == PersonaKind.SOURCE),
        key=lambda p: p.id,
    )
    target_personas = sorted(
        (p for p in libs.personas.values() if p.kind == PersonaKind.TARGET),
        key=lambda p: p.id,
    )
    return {
        "personas": {
            "source": [p.to_dict() for p in source_personas],
            "target": [p.to_dict() for p in target_personas],
        },
        "structures": [libs.structures[k].to_dict() for k in sorted(libs.structures)],
        "modalities": [libs.modalities[k].to_dict() for k in sorted(libs.modalities)],
        "authors": [a.to_dict() for a in list_authors(Path(authors_dir))],
        "backends": [
            str(BackendKind.RULES),
            str(BackendKind.CLAUDE),
            str(BackendKind.AGY),
        ],
    }


def backend_status(
    *,
    timeout: float = 20.0,
    runner: CommandRunner | None = None,
) -> BackendStatusReport:
    """Report availability and version details for all realization backends."""
    return llm.status(timeout=timeout, runner=runner)


def author_build(
    author_id: str,
    display_name: str,
    inputs: Sequence[str | Path],
    *,
    authors_dir: Path = Path("authors"),
    aliases: Sequence[str] = (),
    email: str | None = None,
    min_words: int = 150,
    strict_authors: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Build and atomically save an author's generated profile (and private local email if given)."""
    if not AUTHOR_ID_RE.fullmatch(author_id):
        raise SecurityError(f"Invalid author ID: {author_id!r}")

    base_dir = Path(authors_dir)
    target_path = base_dir / f"{author_id}.yaml"
    # Check tamper protection BEFORE running expensive corpus analysis (TC-031).
    check_profile_writable(target_path, force=force)

    profile = build_profile(
        author_id,
        display_name,
        inputs,
        aliases=aliases,
        strict_authors=strict_authors,
        min_words=min_words,
    )
    save_profile(target_path, profile, force=force)
    if email is not None and email.strip():
        write_local_email(base_dir, author_id, email.strip())
    return profile


def author_inspect(
    author_ref: str,
    *,
    authors_dir: Path = Path("authors"),
) -> dict[str, Any]:
    """Inspect an author profile's metadata, companion layers, and curated/local drift."""
    profile_path = find_profile(author_ref, Path(authors_dir), allow_path=True)
    generated = load_profile(profile_path)
    stem = profile_path.stem
    curated_path = profile_path.parent / f"{stem}.curated.yaml"
    local_path = profile_path.parent / f"{stem}.local.yaml"
    curated = _load_optional_layer(curated_path)
    local = _load_optional_layer(local_path)
    drift = drift_report(generated, curated=curated, local=local)

    author_block = generated.get("author")
    author_map = author_block if isinstance(author_block, dict) else {}
    corpus_block = generated.get("corpus")
    corpus_map = corpus_block if isinstance(corpus_block, dict) else {}

    return {
        "id": str(author_map.get("id") or stem),
        "display_name": str(author_map.get("display_name") or stem),
        "schema_version": int(generated.get("schema_version", 1)),
        "corpus": {
            "document_count": int(corpus_map.get("document_count", 0)),
            "total_words": int(corpus_map.get("total_words", 0)),
            "avg_doc_words": float(corpus_map.get("avg_doc_words", 0.0)),
        },
        "has_curated": curated_path.is_file(),
        "has_local": local_path.is_file(),
        "drift": drift.to_dict(),
    }


def author_show(
    author_ref: str,
    *,
    authors_dir: Path = Path("authors"),
    resolved: bool = False,
    overlay: str | None = None,
) -> dict[str, Any]:
    """Return raw or layer-resolved YAML profile dictionary for an author."""
    profile_path = find_profile(author_ref, Path(authors_dir), allow_path=True)
    if resolved or overlay:
        overlays = (overlay,) if overlay else ()
        merged, _ = load_resolved_profile(profile_path, overlays=overlays)
        return merged
    return load_profile(profile_path)


def author_list(*, authors_dir: Path = Path("authors")) -> list[AuthorSummary]:
    """List all generated author profiles in ``authors_dir``."""
    return list_authors(Path(authors_dir))


def author_diff(
    author_a: str,
    author_b: str,
    *,
    authors_dir: Path = Path("authors"),
) -> AuthorDiff:
    """Compare two author profiles across all 32 stability features."""
    base = Path(authors_dir)
    path_a = find_profile(author_a, base, allow_path=True)
    path_b = find_profile(author_b, base, allow_path=True)
    prof_a, _ = load_resolved_profile(path_a)
    prof_b, _ = load_resolved_profile(path_b)
    return diff_authors(prof_a, prof_b)
