"""AsciiDoc, reStructuredText, and Emacs Org-mode document loaders (Rank 2)."""

from __future__ import annotations

import re

from casper.documents import sha256_bytes
from casper.loaders.markdown import KEY_VALUE_LINE_RE
from casper.models import Block, BlockKind, Document

# --- AsciiDoc patterns ---
_ADOC_HEADING_RE = re.compile(r"^(={1,6})\s+(.+?)\s*$")
_ADOC_ATTR_RE = re.compile(r"^:([A-Za-z0-9_-]+):\s*(.*)$")
_ADOC_LIST_RE = re.compile(r"^(\s*)(?:\*{1,5}|-|\.{1,5})\s+(.+)$")
_ADOC_LINK_RE = re.compile(r"(?:https?://[^\s\[]+|link:[^\s\[]+)\[([^\]]*)\]")
_ADOC_BLOCK_ATTR_RE = re.compile(r"^\[[^\[\]]+\]$")

# --- reStructuredText patterns ---
_RST_ADORNMENT_RE = re.compile(r"^([=\-~^\"+])\1{2,}\s*$")
_RST_LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)]|#[.)])\s+(.+)$")
_RST_DIRECTIVE_RE = re.compile(r"^\.\.(?:\s+.*)?$")
_RST_LINK_RE = re.compile(r"`([^`<]+?)\s*<[^>]+>`_+")

# --- Org-mode patterns ---
_ORG_META_RE = re.compile(r"^#\+([A-Za-z0-9_-]+):\s*(.*)$")
_ORG_HEADING_RE = re.compile(r"^(\*{1,6})\s+(.+?)\s*$")
_ORG_LIST_RE = re.compile(r"^(\s*)(?:[-+]|\d+[.)])\s+(.+)$")
_ORG_LINK_LABEL_RE = re.compile(r"\[\[([^\]]+)\]\[([^\]]+)\]\]")
_ORG_LINK_BARE_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _clean_asciidoc_inline(text: str) -> tuple[str, int]:
    links = len(_ADOC_LINK_RE.findall(text))
    cleaned = _ADOC_LINK_RE.sub(lambda m: m.group(1) or m.group(0), text)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, links


def _clean_rst_inline(text: str) -> tuple[str, int]:
    links = len(_RST_LINK_RE.findall(text))
    cleaned = _RST_LINK_RE.sub(r"\1", text)
    cleaned = re.sub(r"``([^`]+)``", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`_?", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, links


def _clean_org_inline(text: str) -> tuple[str, int]:
    links = len(_ORG_LINK_LABEL_RE.findall(text)) + len(
        _ORG_LINK_BARE_RE.findall(_ORG_LINK_LABEL_RE.sub("", text))
    )
    cleaned = _ORG_LINK_LABEL_RE.sub(r"\2", text)
    cleaned = _ORG_LINK_BARE_RE.sub(r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)/([^/\n]+)/(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)=([^=\n]+)=(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)~([^~\n]+)~(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, links


def parse_asciidoc(data: bytes, source: str) -> Document:
    """Parse an AsciiDoc document into a Casper Document."""
    raw_text = data.decode("utf-8", errors="replace")
    title: str | None = None
    authors: list[str] = []
    published: str | None = None
    description: str | None = None

    blocks: list[Block] = []
    para_buf: list[str] = []
    in_comment_block = False
    in_code_block = False
    code_buf: list[str] = []

    def flush_para() -> None:
        if not para_buf:
            return
        cleaned, links = _clean_asciidoc_inline(" ".join(para_buf))
        if cleaned:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned, links=links))
        para_buf.clear()

    for line in raw_text.splitlines():
        stripped = line.strip()

        if stripped == "////":
            flush_para()
            in_comment_block = not in_comment_block
            continue
        if in_comment_block:
            continue

        if stripped in {"----", "...."}:
            flush_para()
            if in_code_block:
                code_text = "\n".join(code_buf).strip()
                if code_text:
                    blocks.append(Block(kind=BlockKind.CODE, text=code_text))
                code_buf.clear()
                in_code_block = False
            else:
                in_code_block = True
            continue
        if in_code_block:
            code_buf.append(line)
            continue

        if not stripped:
            flush_para()
            continue

        if stripped.startswith("//"):
            flush_para()
            continue

        m_attr = _ADOC_ATTR_RE.match(stripped)
        if m_attr:
            flush_para()
            attr_name = m_attr.group(1).lower()
            attr_val = m_attr.group(2).strip()
            if attr_name == "author" and attr_val:
                authors.append(attr_val)
            elif attr_name in {"revdate", "date"} and attr_val and not published:
                published = attr_val
            elif attr_name == "description" and attr_val and not description:
                description = attr_val
            continue

        if _ADOC_BLOCK_ATTR_RE.match(stripped):
            flush_para()
            continue

        if KEY_VALUE_LINE_RE.match(stripped):
            flush_para()
            cleaned, links = _clean_asciidoc_inline(stripped)
            if cleaned:
                blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned, links=links))
            continue

        m_head = _ADOC_HEADING_RE.match(stripped)
        if m_head:
            flush_para()
            level = len(m_head.group(1))
            htext, links = _clean_asciidoc_inline(m_head.group(2))
            if htext:
                if level == 1 and not title:
                    title = htext
                kind = BlockKind.TITLE if level == 1 else BlockKind.HEADING
                blocks.append(Block(kind=kind, text=htext, level=level, links=links))
            continue

        m_list = _ADOC_LIST_RE.match(line)
        if m_list:
            flush_para()
            indent = len(m_list.group(1))
            item_text, links = _clean_asciidoc_inline(m_list.group(2))
            if item_text:
                blocks.append(
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text=item_text,
                        level=1 + indent // 2,
                        links=links,
                    )
                )
            continue

        para_buf.append(stripped)

    if in_code_block and code_buf:
        code_text = "\n".join(code_buf).strip()
        if code_text:
            blocks.append(Block(kind=BlockKind.CODE, text=code_text))
    flush_para()

    return Document(
        source=source,
        format="asciidoc",
        title=title,
        authors=tuple(authors),
        published=published,
        description=description,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )


def parse_rst(data: bytes, source: str) -> Document:
    """Parse a reStructuredText document into a Casper Document."""
    raw_text = data.decode("utf-8", errors="replace")
    lines = raw_text.splitlines()
    title: str | None = None
    blocks: list[Block] = []
    para_buf: list[str] = []
    heading_styles: dict[tuple[str, bool], int] = {}

    def flush_para() -> None:
        if not para_buf:
            return
        cleaned, links = _clean_rst_inline(" ".join(para_buf))
        if cleaned:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned, links=links))
        para_buf.clear()

    def _level_for(char: str, overlined: bool) -> int:
        key = (char, overlined)
        if key not in heading_styles:
            heading_styles[key] = min(6, len(heading_styles) + 1)
        return heading_styles[key]

    i = 0
    n = len(lines)
    in_directive = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if in_directive:
            if not stripped:
                i += 1
                continue
            if line[0].isspace():
                i += 1
                continue
            in_directive = False

        if not stripped:
            flush_para()
            i += 1
            continue

        if _RST_DIRECTIVE_RE.match(stripped):
            flush_para()
            in_directive = True
            i += 1
            continue

        # Overlined + underlined heading: ====\nTitle\n====
        m_over = _RST_ADORNMENT_RE.match(stripped)
        if m_over and i + 2 < n:
            mid = lines[i + 1].strip()
            under = lines[i + 2].strip()
            m_under = _RST_ADORNMENT_RE.match(under)
            if mid and m_under and m_under.group(1) == m_over.group(1):
                flush_para()
                level = _level_for(m_over.group(1), True)
                htext, links = _clean_rst_inline(mid)
                if htext:
                    if level == 1 and not title:
                        title = htext
                    kind = BlockKind.TITLE if level == 1 else BlockKind.HEADING
                    blocks.append(Block(kind=kind, text=htext, level=level, links=links))
                i += 3
                continue

        # Underlined heading: Title\n=====
        if i + 1 < n and not line[0].isspace() and not _RST_LIST_RE.match(line):
            next_stripped = lines[i + 1].strip()
            m_under = _RST_ADORNMENT_RE.match(next_stripped)
            if m_under and len(next_stripped) >= min(3, len(stripped)):
                flush_para()
                level = _level_for(m_under.group(1), False)
                htext, links = _clean_rst_inline(stripped)
                if htext:
                    if level == 1 and not title:
                        title = htext
                    kind = BlockKind.TITLE if level == 1 else BlockKind.HEADING
                    blocks.append(Block(kind=kind, text=htext, level=level, links=links))
                i += 2
                continue

        if KEY_VALUE_LINE_RE.match(stripped):
            flush_para()
            cleaned, links = _clean_rst_inline(stripped)
            if cleaned:
                blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned, links=links))
            i += 1
            continue

        m_list = _RST_LIST_RE.match(line)
        if m_list:
            flush_para()
            indent = len(m_list.group(1))
            item_text, links = _clean_rst_inline(m_list.group(2))
            if item_text:
                blocks.append(
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text=item_text,
                        level=1 + indent // 2,
                        links=links,
                    )
                )
            i += 1
            continue

        para_buf.append(stripped)
        i += 1

    flush_para()

    return Document(
        source=source,
        format="rst",
        title=title,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )


def parse_org(data: bytes, source: str) -> Document:
    """Parse an Emacs Org-mode document into a Casper Document."""
    raw_text = data.decode("utf-8", errors="replace")
    title: str | None = None
    authors: list[str] = []
    published: str | None = None
    description: str | None = None

    blocks: list[Block] = []
    para_buf: list[str] = []

    def flush_para() -> None:
        if not para_buf:
            return
        cleaned, links = _clean_org_inline(" ".join(para_buf))
        if cleaned:
            blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned, links=links))
        para_buf.clear()

    for line in raw_text.splitlines():
        stripped = line.strip()

        if not stripped:
            flush_para()
            continue

        m_meta = _ORG_META_RE.match(stripped)
        if m_meta:
            flush_para()
            key = m_meta.group(1).upper()
            val = m_meta.group(2).strip()
            if key == "TITLE" and val:
                cleaned_title, links = _clean_org_inline(val)
                if cleaned_title:
                    title = cleaned_title
                    blocks.append(
                        Block(kind=BlockKind.TITLE, text=cleaned_title, level=1, links=links)
                    )
            elif key == "AUTHOR" and val:
                authors.append(val)
            elif key == "DATE" and val and not published:
                published = val
            elif key == "DESCRIPTION" and val and not description:
                description = val
            continue

        if stripped == "#" or stripped.startswith("# "):
            flush_para()
            continue

        if stripped.startswith("#+"):
            flush_para()
            continue

        if KEY_VALUE_LINE_RE.match(stripped):
            flush_para()
            cleaned, links = _clean_org_inline(stripped)
            if cleaned:
                blocks.append(Block(kind=BlockKind.PARAGRAPH, text=cleaned, links=links))
            continue

        m_head = _ORG_HEADING_RE.match(stripped)
        if m_head:
            flush_para()
            level = len(m_head.group(1))
            htext, links = _clean_org_inline(m_head.group(2))
            if htext:
                if level == 1 and not title:
                    title = htext
                    kind = BlockKind.TITLE
                else:
                    kind = BlockKind.HEADING
                blocks.append(Block(kind=kind, text=htext, level=level, links=links))
            continue

        m_list = _ORG_LIST_RE.match(line)
        if m_list:
            flush_para()
            indent = len(m_list.group(1))
            item_text, links = _clean_org_inline(m_list.group(2))
            if item_text:
                blocks.append(
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text=item_text,
                        level=1 + indent // 2,
                        links=links,
                    )
                )
            continue

        para_buf.append(stripped)

    flush_para()

    return Document(
        source=source,
        format="org",
        title=title,
        authors=tuple(authors),
        published=published,
        description=description,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
