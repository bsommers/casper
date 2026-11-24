"""DOCX document loader with zip-bomb uncompressed size cap (Rank 2)."""

from __future__ import annotations

import io
import zipfile

from docx import Document as DocxDocument

from casper.documents import sha256_bytes
from casper.errors import InputError, SecurityError
from casper.models import Block, BlockKind, Document

MAX_UNCOMPRESSED_CAP = 52_428_800  # 50 MiB


def check_zip_bomb(data: bytes, *, max_bytes: int = 10_485_760) -> zipfile.ZipFile:
    limit = min(5 * max_bytes, MAX_UNCOMPRESSED_CAP)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InputError(f"Corrupt ZIP/Office archive: {exc}") from exc
    total_uncompressed = 0
    for info in zf.infolist():
        if info.file_size < 0:
            zf.close()
            raise SecurityError("Negative zip entry size detected")
        total_uncompressed += info.file_size
        if total_uncompressed > limit:
            zf.close()
            raise SecurityError(
                f"Archive uncompressed size exceeds safety cap ({limit} bytes)"
            )
    return zf


def parse_docx(data: bytes, source: str, *, max_bytes: int = 10_485_760) -> Document:
    zf = check_zip_bomb(data, max_bytes=max_bytes)
    zf.close()
    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise InputError(f"Failed to parse DOCX {source}: {exc}") from exc

    title: str | None = (doc.core_properties.title or "").strip() or None
    author = (doc.core_properties.author or "").strip()
    authors = (author,) if author else ()

    blocks: list[Block] = []
    for para in doc.paragraphs:
        text = " ".join(para.text.split()).strip()
        if not text:
            continue
        style_name = (para.style.name if para.style else "") or ""
        lower_style = style_name.lower()
        if lower_style.startswith("heading"):
            digits = "".join(ch for ch in style_name if ch.isdigit())
            level = int(digits) if digits else 2
            if level == 1 and not title:
                title = text
            kind = BlockKind.TITLE if level == 1 else BlockKind.HEADING
            blocks.append(Block(kind=kind, text=text, level=level))
        elif "title" in lower_style:
            if not title:
                title = text
            blocks.append(Block(kind=BlockKind.TITLE, text=text, level=1))
        elif "list" in lower_style:
            blocks.append(Block(kind=BlockKind.LIST_ITEM, text=text, level=1))
        elif "quote" in lower_style:
            blocks.append(Block(kind=BlockKind.QUOTE, text=text))
        else:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=text))

    return Document(
        source=source,
        format="docx",
        title=title,
        authors=authors,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
