"""PDF document loader via pypdf (Rank 2)."""

from __future__ import annotations

import io
import re

from pypdf import PdfReader

from casper.documents import sha256_bytes
from casper.errors import InputError
from casper.models import Block, BlockKind, Document


def parse_pdf(data: bytes, source: str) -> Document:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise InputError(f"Corrupt or unreadable PDF {source}: {exc}") from exc

    meta = reader.metadata
    title = str(meta.title).strip() if meta and meta.title else None
    author = str(meta.author).strip() if meta and meta.author else None
    authors = (author,) if author else ()

    blocks: list[Block] = []
    try:
        for page in reader.pages:
            raw_text = page.extract_text() or ""
            for chunk in re.split(r"\n\s*\n", raw_text):
                cleaned = " ".join(chunk.split()).strip()
                if cleaned:
                    blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned))
    except Exception as exc:
        raise InputError(f"Failed extracting text from PDF {source}: {exc}") from exc

    return Document(
        source=source,
        format="pdf",
        title=title,
        authors=authors,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
