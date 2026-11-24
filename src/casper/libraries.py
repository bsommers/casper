"""Shipped YAML library loader, project_dir overlay, and combo validation (Rank 1)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from casper.errors import LibraryError
from casper.models import (
    DepthLevel,
    FactKind,
    Glossary,
    JargonLevel,
    Libraries,
    MarkupKind,
    Modality,
    Persona,
    PersonaKind,
    Section,
    Structure,
)

DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_yaml_file(path: Path) -> tuple[Any, bytes]:
    try:
        raw = path.read_bytes()
        parsed = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise LibraryError(f"Failed loading library YAML {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LibraryError(f"Library YAML {path} must be a mapping")
    return parsed, raw


def _as_str_tuple(val: Any, field: str, path: Path) -> tuple[str, ...]:
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise LibraryError(f"{path}: field {field!r} must be a list of strings")
    return tuple(val)


def _as_str_dict(val: Any, field: str, path: Path) -> dict[str, str]:
    if not isinstance(val, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in val.items()
    ):
        raise LibraryError(f"{path}: field {field!r} must be a string->string mapping")
    return dict(val)


def _parse_persona(data: dict[str, Any], path: Path) -> Persona:
    try:
        pid = str(data["id"])
        kind = PersonaKind(str(data["kind"]))
        depth = DepthLevel(str(data["detail_depth"]))
        jargon = JargonLevel(str(data["jargon_level"]))
    except (KeyError, ValueError) as exc:
        raise LibraryError(f"Invalid persona schema in {path}: {exc}") from exc
    return Persona(
        id=pid,
        kind=kind,
        priorities=_as_str_tuple(data.get("priorities"), "priorities", path),
        vocabulary_include=_as_str_tuple(
            data.get("vocabulary_include"), "vocabulary_include", path
        ),
        vocabulary_avoid=_as_str_tuple(data.get("vocabulary_avoid"), "vocabulary_avoid", path),
        detail_depth=depth,
        jargon_level=jargon,
        framing_patterns=_as_str_tuple(data.get("framing_patterns"), "framing_patterns", path),
        typical_concerns=_as_str_tuple(data.get("typical_concerns"), "typical_concerns", path),
        cta_styles=_as_str_tuple(data.get("cta_styles"), "cta_styles", path),
        section_priority=_as_str_tuple(data.get("section_priority"), "section_priority", path),
    )


def _parse_structure(data: dict[str, Any], path: Path) -> Structure:
    try:
        sid = str(data["id"])
        goal = str(data["goal"])
        raw_sections = data["sections"]
    except KeyError as exc:
        raise LibraryError(f"Invalid structure schema in {path}: missing {exc}") from exc
    if not isinstance(raw_sections, list) or not raw_sections:
        raise LibraryError(f"{path}: structure sections must be a non-empty list")

    sections: list[Section] = []
    for item in raw_sections:
        if not isinstance(item, dict):
            raise LibraryError(f"{path}: each section must be a mapping")
        try:
            fks = tuple(FactKind(str(k)) for k in item["fact_kinds"])
            sec = Section(
                name=str(item["name"]),
                purpose=str(item["purpose"]),
                fact_kinds=fks,
                required=bool(item["required"]),
                min_words=int(item["min_words"]),
                max_words=int(item["max_words"]),
                heading=str(item["heading"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise LibraryError(f"Invalid section in {path}: {exc}") from exc
        sections.append(sec)

    return Structure(
        id=sid,
        goal=goal,
        sections=tuple(sections),
        compatible_modalities=_as_str_tuple(
            data.get("compatible_modalities"), "compatible_modalities", path
        ),
        default_target_personas=_as_str_tuple(
            data.get("default_target_personas"), "default_target_personas", path
        ),
    )


def _parse_modality(data: dict[str, Any], path: Path) -> Modality:
    try:
        mid = str(data["id"])
        markup = MarkupKind(str(data["markup"]))
        headings = str(data["headings"])
        if headings not in {"none", "h2", "bold", "slack_bold"}:
            raise ValueError(f"Invalid headings style: {headings}")
        max_words = int(data["max_words"]) if data.get("max_words") is not None else None
        max_chars = int(data["max_chars"]) if data.get("max_chars") is not None else None
        return Modality(
            id=mid,
            markup=markup,
            max_words=max_words,
            max_chars=max_chars,
            title=bool(data["title"]),
            headings=headings,
            bullets=bool(data["bullets"]),
            description=str(data["description"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise LibraryError(f"Invalid modality schema in {path}: {exc}") from exc


def _collect_yaml_files(base_dir: Path, subdir: str) -> list[Path]:
    d = base_dir / subdir
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in {".yaml", ".yml"})


def load_libraries(project_dir: Path | None = None) -> Libraries:
    """Load shipped YAML libraries and optionally overlay from project_dir."""
    roots: list[tuple[str, Path]] = [("shipped", DATA_DIR)]
    if project_dir is not None:
        roots.append(("project", Path(project_dir)))

    digest_entries: list[tuple[str, bytes]] = []
    personas: dict[tuple[PersonaKind, str], Persona] = {}
    structures: dict[str, Structure] = {}
    modalities: dict[str, Modality] = {}
    plain_map: dict[str, str] = {}
    preferred_map: dict[str, str] = {}
    banned_list: list[str] = []
    phrasebank: dict[str, tuple[str, ...]] = {}
    lexicons: dict[str, tuple[str, ...]] = {}

    for prefix, root in roots:
        for path in _collect_yaml_files(root, "personas"):
            data, raw = _load_yaml_file(path)
            digest_entries.append((f"{prefix}/personas/{path.name}", raw))
            p = _parse_persona(data, path)
            personas[(p.kind, p.id)] = p

        for path in _collect_yaml_files(root, "structures"):
            data, raw = _load_yaml_file(path)
            digest_entries.append((f"{prefix}/structures/{path.name}", raw))
            s = _parse_structure(data, path)
            structures[s.id] = s

        for path in _collect_yaml_files(root, "modalities"):
            data, raw = _load_yaml_file(path)
            digest_entries.append((f"{prefix}/modalities/{path.name}", raw))
            m = _parse_modality(data, path)
            modalities[m.id] = m

        for path in _collect_yaml_files(root, "glossaries"):
            data, raw = _load_yaml_file(path)
            digest_entries.append((f"{prefix}/glossaries/{path.name}", raw))
            if "plain" in data:
                plain_map.update(_as_str_dict(data["plain"], "plain", path))
            if "preferred" in data:
                preferred_map.update(_as_str_dict(data["preferred"], "preferred", path))
            if "banned" in data:
                for term in _as_str_tuple(data["banned"], "banned", path):
                    if term not in banned_list:
                        banned_list.append(term)

        pb_path = root / "phrasebank.yaml"
        if pb_path.is_file():
            data, raw = _load_yaml_file(pb_path)
            digest_entries.append((f"{prefix}/phrasebank.yaml", raw))
            for k, v in data.items():
                phrasebank[str(k)] = _as_str_tuple(v, str(k), pb_path)

        lex_path = root / "lexicons.yaml"
        if lex_path.is_file():
            data, raw = _load_yaml_file(lex_path)
            digest_entries.append((f"{prefix}/lexicons.yaml", raw))
            for k, v in data.items():
                lexicons[str(k)] = _as_str_tuple(v, str(k), lex_path)

    # Referential validation
    for struct in structures.values():
        for mid in struct.compatible_modalities:
            if mid not in modalities:
                raise LibraryError(
                    f"Structure {struct.id!r} references unknown modality {mid!r}"
                )
        for tid in struct.default_target_personas:
            if (PersonaKind.TARGET, tid) not in personas:
                raise LibraryError(
                    f"Structure {struct.id!r} references unknown target persona {tid!r}"
                )

    for persona in personas.values():
        for cta in persona.cta_styles:
            if cta not in phrasebank:
                raise LibraryError(
                    f"Persona ({persona.kind}, {persona.id}) references unknown cta_style {cta!r}"
                )

    required_lex = {"transitions", "intensifiers", "hedges", "negations", "function_words"}
    missing_lex = required_lex - set(lexicons)
    if missing_lex:
        raise LibraryError(f"lexicons.yaml missing required keys: {sorted(missing_lex)}")

    h = hashlib.sha256()
    for relpath, raw in sorted(digest_entries, key=lambda item: item[0]):
        h.update(relpath.encode("utf-8"))
        h.update(b"\x00")
        h.update(raw)
        h.update(b"\x00")

    return Libraries(
        personas=personas,
        structures=structures,
        modalities=modalities,
        glossary=Glossary(
            plain=plain_map,
            preferred=preferred_map,
            banned=tuple(banned_list),
        ),
        phrasebank=phrasebank,
        lexicons=lexicons,
        digest=h.hexdigest(),
    )


def check_combo(
    libs: Libraries,
    structure_id: str,
    modality_id: str,
    target_id: str,
    source_id: str | None = None,
) -> None:
    """Validate structure, modality, target persona, optional source persona, and compatibility."""
    if structure_id not in libs.structures:
        valid = ", ".join(sorted(libs.structures))
        raise LibraryError(f"Unknown structure {structure_id!r}. Valid structures: {valid}")
    if modality_id not in libs.modalities:
        valid = ", ".join(sorted(libs.modalities))
        raise LibraryError(f"Unknown modality {modality_id!r}. Valid modalities: {valid}")
    if (PersonaKind.TARGET, target_id) not in libs.personas:
        valid = ", ".join(sorted(pid for k, pid in libs.personas if k == PersonaKind.TARGET))
        raise LibraryError(f"Unknown target persona {target_id!r}. Valid targets: {valid}")
    if source_id is not None and (PersonaKind.SOURCE, source_id) not in libs.personas:
        valid = ", ".join(sorted(pid for k, pid in libs.personas if k == PersonaKind.SOURCE))
        raise LibraryError(f"Unknown source persona {source_id!r}. Valid sources: {valid}")

    structure = libs.structures[structure_id]
    if modality_id not in structure.compatible_modalities:
        compat = ", ".join(structure.compatible_modalities)
        raise LibraryError(
            f"Modality {modality_id!r} is incompatible with structure {structure_id!r}. "
            f"Compatible modalities: {compat}"
        )
