"""Author profile catalog discovery, safe profile resolution, and profile diffing (Rank 4)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from casper.errors import ProfileNotFoundError, SecurityError
from casper.features.stability import FEATURE_SPECS, extract_path
from casper.models import AuthorDiff, AuthorSummary
from casper.profile import load_profile

AUTHOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_COMPANION_SUFFIXES: tuple[str, ...] = (".curated.yaml", ".local.yaml")


def _is_primary_profile_file(path: Path) -> bool:
    name = path.name
    if not path.is_file():
        return False
    if name.startswith(".") or ".tmp." in name:
        return False
    if not name.endswith(".yaml"):
        return False
    if name.endswith(_COMPANION_SUFFIXES):
        return False
    return True


def list_authors(authors_dir: Path) -> list[AuthorSummary]:
    """Scan ``authors_dir`` for generated author profiles and return sorted summaries."""
    base_dir = Path(authors_dir)
    if not base_dir.is_dir():
        return []

    summaries: list[AuthorSummary] = []
    for entry in sorted(base_dir.iterdir(), key=lambda p: p.name):
        if not _is_primary_profile_file(entry):
            continue
        prof = load_profile(entry)
        stem = entry.stem

        author_block = prof.get("author")
        author_map = author_block if isinstance(author_block, dict) else {}
        author_id = str(author_map.get("id") or stem)
        display_name = str(author_map.get("display_name") or author_id)

        corpus_block = prof.get("corpus")
        corpus_map = corpus_block if isinstance(corpus_block, dict) else {}
        sources = prof.get("sources")
        source_count = (
            len(sources)
            if isinstance(sources, list) and len(sources) > 0
            else int(corpus_map.get("document_count", 0))
        )
        total_words = int(corpus_map.get("total_words", 0))
        schema_version = int(prof.get("schema_version", 1))

        summaries.append(
            AuthorSummary(
                id=author_id,
                display_name=display_name,
                source_count=source_count,
                total_words=total_words,
                has_curated=(base_dir / f"{stem}.curated.yaml").is_file(),
                has_local=(base_dir / f"{stem}.local.yaml").is_file(),
                schema_version=schema_version,
            )
        )

    summaries.sort(key=lambda s: s.id)
    return summaries


def find_profile(
    author_ref: str,
    authors_dir: Path,
    *,
    allow_path: bool = True,
) -> Path:
    """Resolve an author ID (or direct YAML path when ``allow_path=True``) to a profile file."""
    if not isinstance(author_ref, str) or "\x00" in author_ref:
        raise SecurityError(f"Invalid author profile reference: {author_ref!r}")

    base = Path(authors_dir).resolve()

    if not allow_path:
        if not AUTHOR_ID_RE.fullmatch(author_ref):
            raise SecurityError(f"Invalid author ID: {author_ref!r}")
        candidate = (base / f"{author_ref}.yaml").resolve()
        if not candidate.is_relative_to(base):
            raise SecurityError(f"Author profile path escapes authors_dir: {author_ref!r}")
        if not candidate.is_file():
            raise ProfileNotFoundError(f"Author profile not found: {author_ref}")
        return candidate

    if not author_ref.strip():
        raise ProfileNotFoundError("Author profile not found: empty reference")

    looks_like_path = (
        "/" in author_ref
        or "\\" in author_ref
        or author_ref.endswith((".yaml", ".yml"))
    )
    direct = Path(author_ref)
    if looks_like_path or direct.is_file():
        if direct.is_file():
            return direct
        raise ProfileNotFoundError(f"Author profile not found: {author_ref}")

    if not AUTHOR_ID_RE.fullmatch(author_ref):
        if ".." in author_ref or "/" in author_ref or "\\" in author_ref:
            raise SecurityError(f"Invalid author ID: {author_ref!r}")

    candidate = (base / f"{author_ref}.yaml").resolve()
    if not candidate.is_relative_to(base):
        raise SecurityError(f"Author profile path escapes authors_dir: {author_ref!r}")
    if not candidate.is_file():
        raise ProfileNotFoundError(f"Author profile not found: {author_ref}")
    return candidate


def _extract_stdev(profile: dict[str, Any], key: str) -> float:
    stability = profile.get("stability")
    if not isinstance(stability, dict):
        return 0.0
    entry = stability.get(key)
    if not isinstance(entry, dict):
        return 0.0
    return float(entry.get("stdev", 0.0))


def diff_authors(profile_a: dict[str, Any], profile_b: dict[str, Any]) -> AuthorDiff:
    """Compute normalized per-feature deltas across all 32 ``STABILITY_KEYS``."""
    author_a_block = profile_a.get("author")
    author_b_block = profile_b.get("author")
    author_a = str(
        author_a_block.get("id", "author_a") if isinstance(author_a_block, dict) else "author_a"
    )
    author_b = str(
        author_b_block.get("id", "author_b") if isinstance(author_b_block, dict) else "author_b"
    )

    entries: list[dict[str, Any]] = []
    for spec in FEATURE_SPECS:
        val_a = float(extract_path(profile_a, spec.profile_path))
        val_b = float(extract_path(profile_b, spec.profile_path))
        stdev_a = _extract_stdev(profile_a, spec.key)
        stdev_b = _extract_stdev(profile_b, spec.key)
        delta = val_b - val_a
        scale = max(spec.floor, 0.5 * (stdev_a + stdev_b), 0.1 * max(abs(val_a), abs(val_b)))
        normalized_delta = delta / scale
        entries.append(
            {
                "feature": spec.key,
                "dimension": spec.dimension,
                "value_a": val_a,
                "value_b": val_b,
                "delta": delta,
                "normalized_delta": normalized_delta,
            }
        )

    entries.sort(key=lambda item: (-abs(float(item["normalized_delta"])), str(item["feature"])))
    return AuthorDiff(author_a=author_a, author_b=author_b, feature_deltas=tuple(entries))
