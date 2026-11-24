"""RTF document loader via striprtf (Rank 2)."""

from __future__ import annotations

from striprtf.striprtf import rtf_to_text

from casper.documents import sha256_bytes
from casper.errors import InputError
from casper.models import Block, BlockKind, Document


def parse_rtf(data: bytes, source: str) -> Document:
    try:
        raw_str = data.decode("utf-8", errors="replace")
        plain = rtf_to_text(raw_str)
    except Exception as exc:
        raise InputError(f"Failed to parse RTF {source}: {exc}") from exc

    blocks: list[Block] = []
    for line in plain.splitlines():
        cleaned = " ".join(line.split()).strip()
        if cleaned:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned))

    return Document(
        source=source,
        format="rtf",
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
