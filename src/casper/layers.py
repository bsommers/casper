"""Three-layer profile resolution, drift reporting, and atomic private local storage (Rank 3)."""

from __future__ import annotations

import copy
import os
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from casper.errors import ProfileError, SecurityError
from casper.features.stability import FEATURE_SPEC_BY_KEY, STABILITY_KEYS, extract_path
from casper.models import DriftIssue, DriftReport
from casper.profile import load_profile

_LIST_OP_KEYS: frozenset[str] = frozenset({"$add", "$remove", "$replace"})


def _is_list_op(value: Any) -> bool:
    return isinstance(value, dict) and any(
        isinstance(k, str) and k.startswith("$") for k in value
    )


def _is_valid_style_guide_object(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value.keys()) == {"area", "rule"}
        and isinstance(value["area"], str)
        and isinstance(value["rule"], str)
    )


def _record_generated_provenance(
    obj: Any,
    prefix: str,
    provenance: dict[str, str],
) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if path == "style_guide" and isinstance(val, list):
                for entry in val:
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                        provenance[f"style_guide.{entry['id']}"] = "generated"
            elif isinstance(val, dict):
                _record_generated_provenance(val, path, provenance)
            else:
                provenance[path] = "generated"


def _clear_child_provenance(prefix: str, provenance: dict[str, str]) -> None:
    dot_prefix = f"{prefix}."
    for key in [k for k in provenance if k.startswith(dot_prefix)]:
        del provenance[key]


def _apply_list_op(existing: Any, op: dict[str, Any], path: str) -> list[Any]:
    unknown = [k for k in op if k not in _LIST_OP_KEYS]
    if unknown:
        raise ProfileError(
            f"Unknown list directive key(s) at '{path}': {', '.join(sorted(map(str, unknown)))}. "
            f"Allowed keys: {', '.join(sorted(_LIST_OP_KEYS))}"
        )
    if existing is not None and not isinstance(existing, list):
        raise ProfileError(f"Cannot apply list directive to non-list target at '{path}'")

    for key, val in op.items():
        if not isinstance(val, list):
            raise ProfileError(f"List directive '{key}' at '{path}' must be a list")

    if "$replace" in op:
        return copy.deepcopy(op["$replace"])

    base: list[Any] = copy.deepcopy(existing) if isinstance(existing, list) else []
    to_remove: list[Any] = op.get("$remove", [])
    to_add: list[Any] = op.get("$add", [])

    result = [item for item in base if item not in to_remove]
    for item in to_add:
        if item not in result:
            result.append(copy.deepcopy(item))
    return result


def _merge_style_guide(
    merged: dict[str, Any],
    edits: Any,
    layer_name: str,
    provenance: dict[str, str],
) -> None:
    if isinstance(edits, list):
        raise ProfileError(
            "Plain list assignment to 'style_guide' in a higher layer is forbidden; "
            "use an id-keyed mapping of rule edits"
        )
    if not isinstance(edits, dict):
        raise ProfileError("Higher-layer 'style_guide' must be an id-keyed mapping")

    entries = merged.get("style_guide")
    if not isinstance(entries, list):
        entries = []
        merged["style_guide"] = entries

    for rule_id, edit in edits.items():
        rid = str(rule_id)
        match_idx = next(
            (i for i, item in enumerate(entries) if isinstance(item, dict) and item.get("id") == rid),
            None,
        )
        if edit == "$remove":
            if match_idx is not None:
                del entries[match_idx]
                provenance[f"style_guide.{rid}"] = layer_name
        elif isinstance(edit, str):
            if match_idx is not None:
                entries[match_idx]["rule"] = edit
                provenance[f"style_guide.{rid}"] = layer_name
        elif _is_valid_style_guide_object(edit):
            if match_idx is not None:
                entries[match_idx]["area"] = edit["area"]
                entries[match_idx]["rule"] = edit["rule"]
            else:
                entries.append({"id": rid, "area": edit["area"], "rule": edit["rule"]})
            provenance[f"style_guide.{rid}"] = layer_name
        # Invalid/unknown edit shapes are ignored during merge and flagged by drift_report.


def _merge_mapping(
    target: dict[str, Any],
    incoming: dict[str, Any],
    layer_name: str,
    prefix: str,
    provenance: dict[str, str],
) -> None:
    for raw_key, value in incoming.items():
        key = str(raw_key)
        if not prefix and key == "overlays":
            continue
        path = f"{prefix}.{key}" if prefix else key

        if not prefix and key == "style_guide":
            _merge_style_guide(target, value, layer_name, provenance)
            continue

        if isinstance(value, list):
            raise ProfileError(
                f"Plain list assignment at '{path}' in layer '{layer_name}' is forbidden; "
                "use a mapping with $add, $remove, and/or $replace"
            )

        existing = target.get(key)

        if _is_list_op(value):
            target[key] = _apply_list_op(existing, value, path)
            _clear_child_provenance(path, provenance)
            provenance[path] = layer_name
            continue

        if isinstance(value, dict):
            if isinstance(existing, list):
                raise ProfileError(
                    f"Cannot merge plain mapping into list at '{path}' in layer '{layer_name}'; "
                    "use $add, $remove, and/or $replace"
                )
            if not isinstance(existing, dict):
                provenance.pop(path, None)
                existing = {}
                target[key] = existing
            _merge_mapping(existing, value, layer_name, path, provenance)
            continue

        # Scalar value replaces existing value.
        target[key] = copy.deepcopy(value)
        _clear_child_provenance(path, provenance)
        provenance[path] = layer_name


def _get_overlay_mapping(
    layer: dict[str, Any] | None,
    layer_label: str,
    overlay_name: str,
) -> dict[str, Any] | None:
    if not layer or "overlays" not in layer or layer["overlays"] is None:
        return None
    overlays_obj = layer["overlays"]
    if not isinstance(overlays_obj, dict):
        raise ProfileError(f"'{layer_label}.overlays' must be a mapping")
    entry = overlays_obj.get(overlay_name)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ProfileError(f"Overlay '{layer_label}.overlays.{overlay_name}' must be a mapping")
    return entry


def resolve(
    generated: dict[str, Any],
    curated: dict[str, Any] | None = None,
    local: dict[str, Any] | None = None,
    *,
    overlays: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve generated, curated, local, and named overlay layers into (profile, provenance)."""
    if not isinstance(generated, dict):
        raise ProfileError("Generated profile must be a mapping")
    if curated is not None and not isinstance(curated, dict):
        raise ProfileError("Curated layer must be a mapping")
    if local is not None and not isinstance(local, dict):
        raise ProfileError("Local layer must be a mapping")

    merged = copy.deepcopy(generated)
    merged.pop("overlays", None)

    provenance: dict[str, str] = {}
    _record_generated_provenance(merged, "", provenance)

    if curated:
        _merge_mapping(merged, curated, "curated", "", provenance)
    if local:
        _merge_mapping(merged, local, "local", "", provenance)

    for overlay_name in overlays:
        curated_overlay = _get_overlay_mapping(curated, "curated", overlay_name)
        if curated_overlay:
            _merge_mapping(
                merged,
                curated_overlay,
                f"curated.overlays.{overlay_name}",
                "",
                provenance,
            )
        local_overlay = _get_overlay_mapping(local, "local", overlay_name)
        if local_overlay:
            _merge_mapping(
                merged,
                local_overlay,
                f"local.overlays.{overlay_name}",
                "",
                provenance,
            )

    merged.pop("overlays", None)
    return merged, provenance


def _load_optional_layer(layer_path: Path) -> dict[str, Any] | None:
    if not layer_path.exists():
        return None
    if not layer_path.is_file():
        raise ProfileError(f"Profile layer path is not a file: {layer_path}")
    try:
        raw = layer_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProfileError(f"Failed loading profile layer YAML {layer_path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProfileError(f"Profile layer YAML {layer_path} must be a mapping")
    return data


def load_resolved_profile(
    profile_path: Path,
    *,
    overlays: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, str]]:
    """Load `<id>.yaml` plus optional `.curated.yaml` and `.local.yaml` companions and resolve."""
    path = Path(profile_path)
    generated = load_profile(path)
    curated = _load_optional_layer(path.parent / f"{path.stem}.curated.yaml")
    local = _load_optional_layer(path.parent / f"{path.stem}.local.yaml")
    return resolve(generated, curated, local, overlays=overlays)


def extract_pins(profile: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Extract well-formed numeric feature pins (`{feature: {value, stdev?}}`) from a profile."""
    raw_pins = profile.get("pins")
    if not isinstance(raw_pins, dict):
        return {}
    extracted: dict[str, dict[str, float]] = {}
    for key, cfg in raw_pins.items():
        if not isinstance(key, str) or not isinstance(cfg, dict):
            continue
        val = cfg.get("value")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        pin_entry: dict[str, float] = {"value": float(val)}
        stdev = cfg.get("stdev")
        if (
            stdev is not None
            and not isinstance(stdev, bool)
            and isinstance(stdev, (int, float))
        ):
            pin_entry["stdev"] = float(stdev)
        extracted[key] = pin_entry
    return extracted


def _iter_drift_layers(
    curated: dict[str, Any] | None,
    local: dict[str, Any] | None,
) -> list[tuple[str, dict[str, Any]]]:
    layers: list[tuple[str, dict[str, Any]]] = []
    if isinstance(curated, dict):
        layers.append(("curated", curated))
    if isinstance(local, dict):
        layers.append(("local", local))

    for base_label, base_layer in (("curated", curated), ("local", local)):
        if not isinstance(base_layer, dict):
            continue
        overlays_obj = base_layer.get("overlays")
        if isinstance(overlays_obj, dict):
            for overlay_name in sorted(overlays_obj):
                entry = overlays_obj[overlay_name]
                if isinstance(entry, dict):
                    layers.append((f"{base_label}.overlays.{overlay_name}", entry))
    return layers


def drift_report(
    generated: dict[str, Any],
    curated: dict[str, Any] | None = None,
    local: dict[str, Any] | None = None,
) -> DriftReport:
    """Inspect higher layers for orphaned style_guide edits, unscored pins, and drifted pins."""
    author_block = generated.get("author")
    author_id = str(author_block.get("id", "")) if isinstance(author_block, dict) else ""

    raw_sg = generated.get("style_guide")
    generated_rule_ids: set[str] = set()
    if isinstance(raw_sg, list):
        for item in raw_sg:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                generated_rule_ids.add(item["id"])

    raw_stability = generated.get("stability")
    stability_map: dict[str, Any] = raw_stability if isinstance(raw_stability, dict) else {}

    issues: list[DriftIssue] = []

    for layer_label, layer_data in _iter_drift_layers(curated, local):
        sg_edits = layer_data.get("style_guide")
        if isinstance(sg_edits, dict):
            for raw_rule_id, edit in sg_edits.items():
                rule_id = str(raw_rule_id)
                issue_path = f"{layer_label}.style_guide.{rule_id}"
                if edit == "$remove":
                    if rule_id not in generated_rule_ids:
                        issues.append(
                            DriftIssue(
                                kind="orphan_edit",
                                path=issue_path,
                                message=(
                                    f"Rule '{rule_id}' not found in generated style_guide "
                                    "(cannot remove)"
                                ),
                            )
                        )
                elif isinstance(edit, str):
                    if rule_id not in generated_rule_ids:
                        issues.append(
                            DriftIssue(
                                kind="orphan_edit",
                                path=issue_path,
                                message=(
                                    f"Rule '{rule_id}' not found in generated style_guide "
                                    "(cannot override text)"
                                ),
                            )
                        )
                elif not _is_valid_style_guide_object(edit):
                    issues.append(
                        DriftIssue(
                            kind="orphan_edit",
                            path=issue_path,
                            message=(
                                f"Invalid style_guide edit for '{rule_id}': expected string, "
                                "'$remove', or {area, rule} mapping"
                            ),
                        )
                    )

        pins = layer_data.get("pins")
        if isinstance(pins, dict):
            for raw_pin_key, pin_cfg in pins.items():
                pin_key = str(raw_pin_key)
                issue_path = f"{layer_label}.pins.{pin_key}"
                if pin_key not in FEATURE_SPEC_BY_KEY:
                    issues.append(
                        DriftIssue(
                            kind="unscored_pin",
                            path=issue_path,
                            message=(
                                f"Pin '{pin_key}' is not one of the {len(STABILITY_KEYS)} "
                                "scored stability features"
                            ),
                        )
                    )
                    continue

                if not isinstance(pin_cfg, dict):
                    continue
                raw_val = pin_cfg.get("value")
                if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
                    continue

                pin_val = float(raw_val)
                spec = FEATURE_SPEC_BY_KEY[pin_key]
                gen_val = extract_path(generated, spec.profile_path)
                stab_entry = stability_map.get(pin_key)
                gen_stdev = (
                    float(stab_entry.get("stdev", 0.0)) if isinstance(stab_entry, dict) else 0.0
                )
                tolerance = max(gen_stdev, 0.1 * abs(gen_val))
                delta = abs(pin_val - gen_val)
                if delta > tolerance:
                    issues.append(
                        DriftIssue(
                            kind="drifted_pin",
                            path=issue_path,
                            message=(
                                f"Pin '{pin_key}' value {pin_val:.4g} drifts from generated "
                                f"{gen_val:.4g} by {delta:.4g} (> tolerance {tolerance:.4g})"
                            ),
                        )
                    )

    return DriftReport(author_id=author_id, issues=tuple(issues))


def _validate_author_id(author_id: str) -> None:
    if (
        not author_id
        or not author_id.strip()
        or "/" in author_id
        or "\\" in author_id
        or "\x00" in author_id
        or ".." in author_id
        or author_id in {".", ".."}
    ):
        raise SecurityError(f"Invalid author_id for local profile path: {author_id!r}")


def write_local_email(authors_dir: Path, author_id: str, email: str) -> Path:
    """Atomically write `author.email` to `<authors_dir>/<author_id>.local.yaml` with mode 0o600."""
    _validate_author_id(author_id)

    base_dir = Path(authors_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    resolved_dir = base_dir.resolve()

    target_path = base_dir / f"{author_id}.local.yaml"
    if target_path.resolve().parent != resolved_dir:
        raise SecurityError(f"Resolved local profile escapes authors_dir: {author_id!r}")

    existing = _load_optional_layer(target_path)
    data: dict[str, Any] = copy.deepcopy(existing) if existing is not None else {}

    author_block = data.get("author")
    if author_block is None:
        author_block = {}
        data["author"] = author_block
    elif not isinstance(author_block, dict):
        raise ProfileError(f"Expected 'author' mapping in {target_path}")
    author_block["email"] = email

    serialized = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )

    tmp_path = base_dir / f".{author_id}.local.yaml.tmp.{os.getpid()}.{secrets.token_hex(6)}"
    fd: int | None = None
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd = None  # Ownership transferred to file object.
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target_path)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise

    return target_path
