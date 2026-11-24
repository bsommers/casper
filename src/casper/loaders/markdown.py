"""Markdown and plain-text loader with front matter and Key: value block preservation (Rank 2)."""

from __future__ import annotations

import re
from typing import Any

import yaml

from casper.documents import sha256_bytes
from casper.models import Block, BlockKind, Document

KEY_VALUE_LINE_RE = re.compile(
    r"^(status|state|owner|risks?|blocker|next|next steps?|ask|request|"
    r"decision|progress|done|background|context|metric)\s*:\s*.+$",
    re.IGNORECASE,
)

_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_FENCE_RE = re.compile(r"^```")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_EMPH_LEAD_RE = re.compile(r"^\s*(?:\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)")


def _strip_inline_markdown(text: str) -> tuple[str, int, bool]:
    emph_lead = bool(_EMPH_LEAD_RE.match(text))
    # Remove images first
    cleaned = _MD_IMAGE_RE.sub(r"\1", text)
    links = len(_MD_LINK_RE.findall(cleaned))
    cleaned = _MD_LINK_RE.sub(r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, links, emph_lead


def _parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    lines = text.splitlines()
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    raw_fm = "\n".join(lines[1:end_idx])
    try:
        parsed = yaml.safe_load(raw_fm)
    except yaml.YAMLError:
        return {}, text
    if not isinstance(parsed, dict):
        return {}, text
    body = "\n".join(lines[end_idx + 1 :])
    return parsed, body


def parse_markdown(data: bytes, source: str, *, fmt: str = "markdown") -> Document:
    raw_text = data.decode("utf-8", errors="replace")
    fm, body = _parse_front_matter(raw_text)

    title: str | None = str(fm["title"]).strip() if fm.get("title") else None
    authors: list[str] = []
    if isinstance(fm.get("authors"), list):
        authors = [str(a).strip() for a in fm["authors"] if str(a).strip()]
    elif fm.get("author"):
        authors = [str(fm["author"]).strip()]
    published = str(fm["date"]).strip() if fm.get("date") else (
        str(fm["published"]).strip() if fm.get("published") else None
    )
    modified = str(fm["modified"]).strip() if fm.get("modified") else None
    canonical_url = str(fm["canonical_url"]).strip() if fm.get("canonical_url") else None
    description = str(fm["description"]).strip() if fm.get("description") else None

    blocks: list[Block] = []
    para_buf: list[str] = []
    in_code = False
    code_buf: list[str] = []

    def flush_para() -> None:
        if not para_buf:
            return
        joined = " ".join(para_buf)
        cleaned, links, emph_lead = _strip_inline_markdown(joined)
        if cleaned:
            blocks.append(
                Block(
                    kind=BlockKind.PARAGRAPH,
                    text=cleaned,
                    links=links,
                    emphasis_lead=emph_lead,
                )
            )
        para_buf.clear()

    for line in body.splitlines():
        stripped = line.strip()

        if _FENCE_RE.match(stripped):
            flush_para()
            if in_code:
                code_text = "\n".join(code_buf).strip()
                if code_text:
                    blocks.append(Block(kind=BlockKind.CODE, text=code_text))
                code_buf.clear()
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_buf.append(line)
            continue

        if not stripped:
            flush_para()
            continue

        # Key: value line-break preservation BEFORE joining adjacent prose lines
        if KEY_VALUE_LINE_RE.match(stripped):
            flush_para()
            cleaned, links, emph_lead = _strip_inline_markdown(stripped)
            if cleaned:
                blocks.append(
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text=cleaned,
                        links=links,
                        emphasis_lead=emph_lead,
                    )
                )
            continue

        m_head = _ATX_HEADING_RE.match(stripped)
        if m_head:
            flush_para()
            level = len(m_head.group(1))
            htext, links, _ = _strip_inline_markdown(m_head.group(2))
            if htext:
                if level == 1 and not title:
                    title = htext
                kind = BlockKind.TITLE if level == 1 else BlockKind.HEADING
                blocks.append(Block(kind=kind, text=htext, level=level, links=links))
            continue

        m_list = _LIST_ITEM_RE.match(line)
        if m_list:
            flush_para()
            indent = len(m_list.group(1))
            item_text, links, emph_lead = _strip_inline_markdown(m_list.group(2))
            if item_text:
                blocks.append(
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text=item_text,
                        level=1 + indent // 2,
                        links=links,
                        emphasis_lead=emph_lead,
                    )
                )
            continue

        m_quote = _QUOTE_RE.match(stripped)
        if m_quote:
            flush_para()
            qtext, links, emph_lead = _strip_inline_markdown(m_quote.group(1))
            if qtext:
                blocks.append(
                    Block(
                        kind=BlockKind.QUOTE,
                        text=qtext,
                        links=links,
                        emphasis_lead=emph_lead,
                    )
                )
            continue

        para_buf.append(stripped)

    if in_code and code_buf:
        blocks.append(Block(kind=BlockKind.CODE, text="\n".join(code_buf).strip()))
    flush_para()

    return Document(
        source=source,
        format=fmt,
        title=title,
        authors=tuple(authors),
        published=published,
        modified=modified,
        canonical_url=canonical_url,
        description=description,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
