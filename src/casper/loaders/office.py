"""ODT and legacy DOC loaders (Rank 2)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from casper.documents import sha256_bytes
from casper.errors import InputError
from casper.loaders.docx import check_zip_bomb
from casper.models import Block, BlockKind, Document

_ODF_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def parse_odt(data: bytes, source: str, *, max_bytes: int = 10_485_760) -> Document:
    zf = check_zip_bomb(data, max_bytes=max_bytes)
    try:
        content_xml = zf.read("content.xml")
    except KeyError as exc:
        zf.close()
        raise InputError(f"ODT archive missing content.xml: {source}") from exc
    finally:
        zf.close()

    try:
        root = ET.fromstring(content_xml)
    except ET.ParseError as exc:
        raise InputError(f"Malformed ODT content.xml in {source}: {exc}") from exc

    blocks: list[Block] = []
    title: str | None = None
    h_tag = f"{{{_ODF_TEXT_NS}}}h"
    p_tag = f"{{{_ODF_TEXT_NS}}}p"
    outline_attr = f"{{{_ODF_TEXT_NS}}}outline-level"

    for elem in root.iter():
        if elem.tag == h_tag:
            text = " ".join("".join(elem.itertext()).split()).strip()
            if not text:
                continue
            level = int(elem.attrib.get(outline_attr, "2"))
            if level == 1 and not title:
                title = text
            kind = BlockKind.TITLE if level == 1 else BlockKind.HEADING
            blocks.append(Block(kind=kind, text=text, level=level))
        elif elem.tag == p_tag:
            text = " ".join("".join(elem.itertext()).split()).strip()
            if text:
                blocks.append(Block(kind=BlockKind.PARAGRAPH, text=text))

    return Document(
        source=source,
        format="odt",
        title=title,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )


def parse_doc(data: bytes, source: str) -> Document:
    antiword = shutil.which("antiword")
    soffice = shutil.which("soffice")
    if not antiword and not soffice:
        raise InputError(
            f"Legacy .doc format requires 'antiword' or 'soffice' on PATH to load {source}"
        )

    with tempfile.TemporaryDirectory(prefix="casper-doc-") as tmp:
        doc_path = Path(tmp) / "input.doc"
        doc_path.write_bytes(data)
        if antiword:
            proc = subprocess.run(
                [antiword, str(doc_path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode != 0:
                raise InputError(f"antiword failed on {source}: {proc.stderr.strip()}")
            extracted = proc.stdout
        else:
            assert soffice is not None
            proc = subprocess.run(
                [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", tmp, str(doc_path)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            txt_path = Path(tmp) / "input.txt"
            if proc.returncode != 0 or not txt_path.is_file():
                raise InputError(f"soffice failed on {source}: {proc.stderr.strip()}")
            extracted = txt_path.read_text(encoding="utf-8", errors="replace")

    blocks = tuple(
        Block(kind=BlockKind.PARAGRAPH, text=" ".join(ln.split()).strip())
        for ln in extracted.splitlines()
        if ln.strip()
    )
    return Document(
        source=source,
        format="doc",
        blocks=blocks,
        sha256=sha256_bytes(data),
    )
