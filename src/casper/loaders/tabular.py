"""CSV and YAML structured note loaders (Rank 2)."""

from __future__ import annotations

import csv
import io
from typing import Any

import yaml

from casper.documents import sha256_bytes
from casper.errors import InputError
from casper.models import Block, BlockKind, Document


def parse_csv(data: bytes, source: str) -> Document:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"CSV file {source} is not valid UTF-8: {exc}") from exc

    if not text.strip():
        raise InputError(f"CSV file {source} is empty")

    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise InputError(f"Malformed CSV in {source}: {exc}") from exc

    if not rows or not any(cell.strip() for cell in rows[0]):
        raise InputError(f"CSV file {source} has no header row")

    headers = [h.strip() for h in rows[0]]
    blocks: list[Block] = []
    for row_idx, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(headers):
            raise InputError(
                f"Malformed CSV in {source} line {row_idx}: more columns than headers"
            )
        for col_idx, val in enumerate(row):
            cleaned_val = val.strip()
            if not cleaned_val:
                continue
            col_name = headers[col_idx] or f"Column {col_idx + 1}"
            blocks.append(
                Block(kind=BlockKind.PARAGRAPH, text=f"{col_name}: {cleaned_val}")
            )

    return Document(
        source=source,
        format="csv",
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )


def _flatten_yaml(obj: Any, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                lines.extend(_flatten_yaml(v, key))
            elif v is not None:
                val = str(v).strip()
                if val:
                    lines.append(f"{key}: {val}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.extend(_flatten_yaml(item, prefix))
            elif item is not None:
                val = str(item).strip()
                if val:
                    lines.append(f"{prefix}: {val}" if prefix else val)
    elif obj is not None:
        val = str(obj).strip()
        if val:
            lines.append(f"{prefix}: {val}" if prefix else val)
    return lines


def parse_yaml(data: bytes, source: str) -> Document:
    try:
        text = data.decode("utf-8")
        parsed = yaml.safe_load(text)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise InputError(f"Malformed YAML in {source}: {exc}") from exc

    if parsed is None:
        raise InputError(f"YAML file {source} is empty")
    if not isinstance(parsed, (dict, list)):
        raise InputError(f"YAML file {source} must contain a mapping or list")

    title = str(parsed["title"]).strip() if isinstance(parsed, dict) and parsed.get("title") else None
    flattened = _flatten_yaml(parsed)
    blocks = tuple(Block(kind=BlockKind.PARAGRAPH, text=line) for line in flattened)

    return Document(
        source=source,
        format="yaml",
        title=title,
        blocks=blocks,
        sha256=sha256_bytes(data),
    )
