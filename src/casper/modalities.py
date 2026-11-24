"""Modality-specific draft formatting, rendered counting, and multi-format export (Rank 4)."""

from __future__ import annotations

import datetime
import html
import io
import json
import re
import textwrap
import zipfile
from collections.abc import Mapping
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from bs4 import BeautifulSoup, Tag
from docx import Document as DocxDocument

from casper.errors import InputError
from casper.models import Draft, DraftSection, MarkupKind, Modality

_HTML_TAG_RE = re.compile(r"<[^>]+>")

EXPORT_FORMATS: dict[str, tuple[str, str, str]] = {
    "txt": ("Plain Text (.txt)", "txt", "text/plain; charset=utf-8"),
    "md": ("Markdown (.md)", "md", "text/markdown; charset=utf-8"),
    "adoc": ("AsciiDoc (.adoc)", "adoc", "text/asciidoc; charset=utf-8"),
    "html": ("HTML5 Document (.html)", "html", "text/html; charset=utf-8"),
    "pdf": ("PDF Document (.pdf)", "pdf", "application/pdf"),
    "docx": (
        "Microsoft Word (.docx)",
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "odt": (
        "OpenDocument Text (.odt)",
        "odt",
        "application/vnd.oasis.opendocument.text",
    ),
    "rtf": ("Rich Text Format (.rtf)", "rtf", "application/rtf"),
    "tex": ("LaTeX (.tex)", "tex", "application/x-tex"),
    "rst": ("reStructuredText (.rst)", "rst", "text/x-rst; charset=utf-8"),
    "org": ("Emacs Org-mode (.org)", "org", "text/org; charset=utf-8"),
    "json": ("JSON Bundle (.json)", "json", "application/json; charset=utf-8"),
}


def _format_title(title: str, markup: MarkupKind) -> str:
    if markup == MarkupKind.HTML:
        return f"<h1>{html.escape(title)}</h1>"
    if markup == MarkupKind.MARKDOWN:
        return f"# {title}"
    if markup == MarkupKind.SLACK:
        return f"*{title}*"
    return title


def _format_heading(heading: str, modality: Modality) -> str | None:
    if not heading or modality.headings == "none":
        return None
    if modality.markup == MarkupKind.HTML:
        escaped = html.escape(heading)
        if modality.headings == "h2":
            return f"<h2>{escaped}</h2>"
        return f"<strong>{escaped}</strong>"
    if modality.headings == "h2":
        return f"## {heading}"
    if modality.headings == "slack_bold":
        return f"*{heading}*"
    # modality.headings == "bold"
    if modality.markup == MarkupKind.MARKDOWN:
        return f"**{heading}**"
    if modality.markup == MarkupKind.SLACK:
        return f"*{heading}*"
    return heading


def _format_html_section(section: DraftSection, modality: Modality) -> list[str]:
    parts: list[str] = []
    heading_html = _format_heading(section.heading, modality)
    if heading_html is not None:
        parts.append(heading_html)

    body_sents = [s for s in section.sentences if not s.frame]
    frame_sents = [s for s in section.sentences if s.frame]

    if body_sents:
        if modality.bullets and len(body_sents) >= 2:
            items = "\n".join(f"<li>{html.escape(s.text)}</li>" for s in body_sents)
            parts.append(f"<ul>\n{items}\n</ul>")
        else:
            joined = " ".join(html.escape(s.text) for s in body_sents)
            parts.append(f"<p>{joined}</p>")

    for frame_sent in frame_sents:
        parts.append(f"<p>{html.escape(frame_sent.text)}</p>")

    return parts


def _format_text_section(section: DraftSection, modality: Modality) -> list[str]:
    blocks: list[str] = []
    heading_line = _format_heading(section.heading, modality)

    body_sents = [s for s in section.sentences if not s.frame]
    frame_sents = [s for s in section.sentences if s.frame]

    body_str = ""
    if body_sents:
        if modality.bullets and len(body_sents) >= 2:
            body_str = "\n".join(f"- {s.text}" for s in body_sents)
        else:
            body_str = " ".join(s.text for s in body_sents)

    if heading_line is not None and body_str:
        blocks.append(f"{heading_line}\n{body_str}")
    elif heading_line is not None and frame_sents:
        blocks.append(f"{heading_line}\n{frame_sents[0].text}")
        frame_sents = frame_sents[1:]
    elif body_str:
        blocks.append(body_str)

    for frame_sent in frame_sents:
        blocks.append(frame_sent.text)

    return blocks


def format_draft(draft: Draft, modality: Modality) -> str:
    """Format a realized Draft into the target Modality without altering sentence wording."""
    if modality.markup == MarkupKind.HTML:
        elements: list[str] = []
        if modality.title and draft.title:
            elements.append(_format_title(draft.title, MarkupKind.HTML))
        for section in draft.sections:
            if not section.sentences:
                continue
            elements.extend(_format_html_section(section, modality))
        if not elements:
            return ""
        return "<article>\n" + "\n".join(elements) + "\n</article>"

    blocks: list[str] = []
    if modality.title and draft.title:
        blocks.append(_format_title(draft.title, modality.markup))
    for section in draft.sections:
        if not section.sentences:
            continue
        blocks.extend(_format_text_section(section, modality))
    return "\n\n".join(blocks)


def count_rendered(draft: Draft, modality: Modality) -> tuple[int, int]:
    """Return (word_count, char_count) for the formatted draft under the given modality."""
    text = format_draft(draft, modality)
    char_count = len(text)
    if modality.markup == MarkupKind.HTML:
        plain = html.unescape(_HTML_TAG_RE.sub(" ", text))
        word_count = len(plain.split())
        return word_count, char_count

    tokens = [tok for raw in text.split() if (tok := raw.strip("#*-"))]
    return len(tokens), char_count


_MD_H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")
_MD_H2_RE = re.compile(r"^#{2,6}\s+(.+?)\s*#*\s*$")
_MD_BOLD_HEADING_RE = re.compile(r"^\*\*([^*]+)\*\*\s*$")
_SLACK_BOLD_HEADING_RE = re.compile(r"^\*([^*\n]+)\*\s*$")
_BULLET_LINE_RE = re.compile(r"^\s*[-*+]\s+(.+)$")
_HTML_LIKELY_RE = re.compile(
    r"^\s*(?:<!doctype\s+html|<html\b|<article\b|<h[1-6]\b|<p\b|<ul\b|<ol\b|<strong\b)",
    re.IGNORECASE,
)
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_LATEX_ESCAPES: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "#": r"\#",
    "$": r"\$",
    "%": r"\%",
    "&": r"\&",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile(r"[\\#$%&_{}~^]")

_PDF_UNICODE_SUBS = str.maketrans(
    {
        "\u2014": "--",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",
    }
)

_FIXED_ZIP_DT = (2026, 1, 1, 0, 0, 0)
_FIXED_DOCX_DT = datetime.datetime(2026, 1, 1, 0, 0, 0)


def _sanitize_slug(raw: str | None) -> str:
    if not raw:
        return "casper-draft"
    slug = _SLUG_NON_ALNUM_RE.sub("-", raw.lower()).strip("-")
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")
    return slug or "casper-draft"


def _parse_html_elements(text: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(text, "html.parser")
    candidate = soup.find("article") or soup.find("main") or soup.body
    root: Tag | BeautifulSoup = candidate if isinstance(candidate, Tag) else soup
    elements: list[tuple[str, str]] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "p", "li"]):
        if not isinstance(el, Tag):
            continue
        if el.name == "p" and el.find_parent("li") is not None:
            continue
        if el.name == "strong" and el.find_parent(
            ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"]
        ) is not None:
            continue
        cleaned = " ".join(el.get_text(" ", strip=True).split()).strip()
        if not cleaned:
            continue
        if el.name == "h1":
            elements.append(("title", cleaned))
        elif el.name in {"h2", "h3", "h4", "h5", "h6", "strong"}:
            elements.append(("heading", cleaned))
        elif el.name == "li":
            elements.append(("bullet", cleaned))
        else:
            elements.append(("paragraph", cleaned))
    if not elements:
        plain = " ".join(soup.get_text(" ", strip=True).split()).strip()
        if plain:
            elements.append(("paragraph", plain))
    return elements


def _parse_export_elements(text: str) -> list[tuple[str, str]]:
    if _HTML_LIKELY_RE.match(text):
        return _parse_html_elements(text)

    elements: list[tuple[str, str]] = []
    para_buf: list[str] = []

    def flush_para() -> None:
        if not para_buf:
            return
        joined = " ".join(para_buf).strip()
        if joined:
            elements.append(("paragraph", joined))
        para_buf.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_para()
            continue

        m_h1 = _MD_H1_RE.match(stripped)
        if m_h1:
            flush_para()
            elements.append(("title", m_h1.group(1).strip()))
            continue

        m_h2 = _MD_H2_RE.match(stripped)
        if m_h2:
            flush_para()
            elements.append(("heading", m_h2.group(1).strip()))
            continue

        m_bold = _MD_BOLD_HEADING_RE.match(stripped)
        if m_bold:
            flush_para()
            elements.append(("heading", m_bold.group(1).strip()))
            continue

        m_slack = _SLACK_BOLD_HEADING_RE.match(stripped)
        if m_slack:
            flush_para()
            elements.append(("heading", m_slack.group(1).strip()))
            continue

        m_bullet = _BULLET_LINE_RE.match(line)
        if m_bullet:
            flush_para()
            elements.append(("bullet", m_bullet.group(1).strip()))
            continue

        para_buf.append(stripped)

    flush_para()
    return elements


def _escape_latex(text: str) -> str:
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPES[m.group(0)], text)


def _escape_rtf(text: str) -> str:
    parts: list[str] = []
    for ch in text:
        if ch == "\\":
            parts.append(r"\\")
        elif ch == "{":
            parts.append(r"\{")
        elif ch == "}":
            parts.append(r"\}")
        elif ch == "\n":
            parts.append(r"\line ")
        elif ch == "\t":
            parts.append(r"\tab ")
        else:
            cp = ord(ch)
            if 0x20 <= cp <= 0x7E:
                parts.append(ch)
            elif cp <= 0xFFFF:
                signed = cp if cp <= 32767 else cp - 65536
                parts.append(f"\\u{signed}?")
            else:
                adj = cp - 0x10000
                high = 0xD800 + (adj >> 10)
                low = 0xDC00 + (adj & 0x3FF)
                parts.append(f"\\u{high - 65536}?\\u{low - 65536}?")
    return "".join(parts)


def _pdf_escape_string(text: str) -> str:
    normalized = text.translate(_PDF_UNICODE_SUBS)
    raw = normalized.encode("cp1252", errors="replace")
    out: list[str] = []
    for b in raw:
        if b == 0x5C:  # backslash
            out.append(r"\\")
        elif b == 0x28:  # (
            out.append(r"\(")
        elif b == 0x29:  # )
            out.append(r"\)")
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    return "".join(out)


def _export_txt(elements: list[tuple[str, str]]) -> bytes:
    blocks: list[str] = []
    bullet_group: list[str] = []

    def flush_bullets() -> None:
        if bullet_group:
            blocks.append("\n".join(bullet_group))
            bullet_group.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullet_group.append(f"- {content}")
        else:
            flush_bullets()
            blocks.append(content)
    flush_bullets()
    out = "\n\n".join(blocks)
    return (out + ("\n" if out else "")).encode("utf-8")


def _export_md(elements: list[tuple[str, str]]) -> bytes:
    blocks: list[str] = []
    bullet_group: list[str] = []

    def flush_bullets() -> None:
        if bullet_group:
            blocks.append("\n".join(bullet_group))
            bullet_group.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullet_group.append(f"- {content}")
        else:
            flush_bullets()
            if kind == "title":
                blocks.append(f"# {content}")
            elif kind == "heading":
                blocks.append(f"## {content}")
            else:
                blocks.append(content)
    flush_bullets()
    out = "\n\n".join(blocks)
    return (out + ("\n" if out else "")).encode("utf-8")


def _export_adoc(elements: list[tuple[str, str]]) -> bytes:
    blocks: list[str] = []
    bullet_group: list[str] = []

    def flush_bullets() -> None:
        if bullet_group:
            blocks.append("\n".join(bullet_group))
            bullet_group.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullet_group.append(f"* {content}")
        else:
            flush_bullets()
            if kind == "title":
                blocks.append(f"= {content}")
            elif kind == "heading":
                blocks.append(f"== {content}")
            else:
                blocks.append(content)
    flush_bullets()
    out = "\n\n".join(blocks)
    return (out + ("\n" if out else "")).encode("utf-8")


def _export_rst(elements: list[tuple[str, str]]) -> bytes:
    blocks: list[str] = []
    bullet_group: list[str] = []

    def flush_bullets() -> None:
        if bullet_group:
            blocks.append("\n".join(bullet_group))
            bullet_group.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullet_group.append(f"- {content}")
        else:
            flush_bullets()
            if kind == "title":
                underline = "=" * max(len(content), 3)
                blocks.append(f"{content}\n{underline}")
            elif kind == "heading":
                underline = "-" * max(len(content), 3)
                blocks.append(f"{content}\n{underline}")
            else:
                blocks.append(content)
    flush_bullets()
    out = "\n\n".join(blocks)
    return (out + ("\n" if out else "")).encode("utf-8")


def _export_org(elements: list[tuple[str, str]]) -> bytes:
    blocks: list[str] = []
    bullet_group: list[str] = []

    def flush_bullets() -> None:
        if bullet_group:
            blocks.append("\n".join(bullet_group))
            bullet_group.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullet_group.append(f"- {content}")
        else:
            flush_bullets()
            if kind == "title":
                blocks.append(f"#+TITLE: {content}")
            elif kind == "heading":
                blocks.append(f"* {content}")
            else:
                blocks.append(content)
    flush_bullets()
    out = "\n\n".join(blocks)
    return (out + ("\n" if out else "")).encode("utf-8")


def _export_html(elements: list[tuple[str, str]], doc_title: str | None) -> bytes:
    page_title = html.escape(doc_title or "Casper Draft", quote=True)
    body_parts: list[str] = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        if bullets:
            items = "\n".join(f"    <li>{html.escape(item, quote=True)}</li>" for item in bullets)
            body_parts.append(f"  <ul>\n{items}\n  </ul>")
            bullets.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullets.append(content)
        else:
            flush_bullets()
            escaped = html.escape(content, quote=True)
            if kind == "title":
                body_parts.append(f"  <h1>{escaped}</h1>")
            elif kind == "heading":
                body_parts.append(f"  <h2>{escaped}</h2>")
            else:
                body_parts.append(f"  <p>{escaped}</p>")
    flush_bullets()

    article_inner = "\n".join(body_parts)
    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{page_title}</title>\n"
        "</head>\n"
        "<body>\n"
        "<article>\n"
        f"{article_inner}\n"
        "</article>\n"
        "</body>\n"
        "</html>\n"
    )
    return doc.encode("utf-8")


def _export_tex(elements: list[tuple[str, str]], doc_title: str | None) -> bytes:
    lines: list[str] = [
        r"\documentclass{article}",
        r"\usepackage[utf8]{inputenc}",
    ]
    title_emitted = False
    first_title = doc_title or next((c for k, c in elements if k == "title"), None)
    if first_title:
        lines.append(f"\\title{{{_escape_latex(first_title)}}}")
        lines.append(r"\date{}")
        title_emitted = True
    lines.append(r"\begin{document}")
    if title_emitted:
        lines.append(r"\maketitle")

    in_list = False
    skipped_first_title = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            lines.append(r"\end{itemize}")
            in_list = False

    for kind, content in elements:
        if kind == "title" and title_emitted and not skipped_first_title:
            skipped_first_title = True
            continue
        if kind == "bullet":
            if not in_list:
                lines.append("")
                lines.append(r"\begin{itemize}")
                in_list = True
            lines.append(f"  \\item {_escape_latex(content)}")
        else:
            close_list()
            lines.append("")
            if kind in {"title", "heading"}:
                lines.append(f"\\section*{{{_escape_latex(content)}}}")
            else:
                lines.append(_escape_latex(content))

    close_list()
    lines.append("")
    lines.append(r"\end{document}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _export_rtf(elements: list[tuple[str, str]]) -> bytes:
    parts: list[str] = [
        r"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Helvetica;}}\f0\fs24"
    ]
    for kind, content in elements:
        escaped = _escape_rtf(content)
        if kind == "title":
            parts.append(f"{{\\pard\\sb120\\sa180\\b\\fs36 {escaped}\\par}}")
        elif kind == "heading":
            parts.append(f"{{\\pard\\sb180\\sa100\\b\\fs28 {escaped}\\par}}")
        elif kind == "bullet":
            parts.append(f"{{\\pard\\li360\\sa60 - {escaped}\\par}}")
        else:
            parts.append(f"{{\\pard\\sa120 {escaped}\\par}}")
    parts.append("}")
    return ("\n".join(parts) + "\n").encode("utf-8")


def _export_docx(elements: list[tuple[str, str]], doc_title: str | None) -> bytes:
    doc = DocxDocument()
    doc.core_properties.title = doc_title or "Casper Draft"
    doc.core_properties.created = _FIXED_DOCX_DT
    doc.core_properties.modified = _FIXED_DOCX_DT

    for kind, content in elements:
        if kind == "title":
            doc.add_heading(content, level=1)
        elif kind == "heading":
            doc.add_heading(content, level=2)
        elif kind == "bullet":
            doc.add_paragraph(content, style="List Bullet")
        else:
            doc.add_paragraph(content)

    raw_buf = io.BytesIO()
    doc.save(raw_buf)
    raw_buf.seek(0)

    # Re-pack with fixed ZipInfo timestamps for byte-level determinism (GC-03)
    det_buf = io.BytesIO()
    with (
        zipfile.ZipFile(raw_buf, "r") as zin,
        zipfile.ZipFile(det_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout,
    ):
        for name in sorted(zin.namelist()):
            zi = zipfile.ZipInfo(filename=name, date_time=_FIXED_ZIP_DT)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, zin.read(name))
    return det_buf.getvalue()


def _export_odt(elements: list[tuple[str, str]]) -> bytes:
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">\n'
        '  <manifest:file-entry manifest:full-path="/" '
        'manifest:media-type="application/vnd.oasis.opendocument.text"/>\n'
        '  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>\n'
        '  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>\n'
        "</manifest:manifest>\n"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<office:document-styles '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
        'office:version="1.2">\n'
        "  <office:styles/>\n"
        "</office:document-styles>\n"
    )

    body_nodes: list[str] = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        if bullets:
            items = "".join(
                f"<text:list-item><text:p>{xml_escape(b)}</text:p></text:list-item>"
                for b in bullets
            )
            body_nodes.append(f"<text:list>{items}</text:list>")
            bullets.clear()

    for kind, content in elements:
        if kind == "bullet":
            bullets.append(content)
        else:
            flush_bullets()
            escaped = xml_escape(content)
            if kind == "title":
                body_nodes.append(f'<text:h text:outline-level="1">{escaped}</text:h>')
            elif kind == "heading":
                body_nodes.append(f'<text:h text:outline-level="2">{escaped}</text:h>')
            else:
                body_nodes.append(f"<text:p>{escaped}</text:p>")
    flush_bullets()

    content_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.2">\n'
        "  <office:body>\n"
        "    <office:text>\n"
        + "\n".join(f"      {node}" for node in body_nodes)
        + "\n    </office:text>\n"
        "  </office:body>\n"
        "</office:document-content>\n"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # ODF requires mimetype first and stored uncompressed
        mime_info = zipfile.ZipInfo(filename="mimetype", date_time=_FIXED_ZIP_DT)
        mime_info.compress_type = zipfile.ZIP_STORED
        zf.writestr(mime_info, b"application/vnd.oasis.opendocument.text")

        for fname, payload in (
            ("META-INF/manifest.xml", manifest_xml.encode("utf-8")),
            ("styles.xml", styles_xml.encode("utf-8")),
            ("content.xml", content_xml.encode("utf-8")),
        ):
            zi = zipfile.ZipInfo(filename=fname, date_time=_FIXED_ZIP_DT)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, payload)
    return buf.getvalue()


def _export_pdf(elements: list[tuple[str, str]], doc_title: str | None) -> bytes:
    page_width = 612
    page_height = 792
    margin_x = 54
    top_y = 738
    bottom_y = 54

    # (font_ref, font_size, leading, x_pos, text)
    pages: list[list[tuple[str, int, int, int, str]]] = [[]]
    y = top_y

    def ensure_space(needed: int) -> None:
        nonlocal y
        if y - needed < bottom_y and pages[-1]:
            pages.append([])
            y = top_y

    for kind, content in elements:
        if kind == "title":
            font, size, leading, width, x_pos, space_before, space_after = (
                "/F2",
                18,
                24,
                48,
                margin_x,
                0,
                10,
            )
            wrapped = textwrap.wrap(
                content, width=width, break_long_words=True, break_on_hyphens=False
            ) or [content]
        elif kind == "heading":
            font, size, leading, width, x_pos, space_before, space_after = (
                "/F2",
                13,
                18,
                66,
                margin_x,
                8,
                4,
            )
            wrapped = textwrap.wrap(
                content, width=width, break_long_words=True, break_on_hyphens=False
            ) or [content]
        elif kind == "bullet":
            font, size, leading, width, x_pos, space_before, space_after = (
                "/F1",
                11,
                15,
                76,
                margin_x + 14,
                0,
                3,
            )
            raw_lines = textwrap.wrap(
                content, width=width, break_long_words=True, break_on_hyphens=False
            ) or [content]
            wrapped = [
                f"- {ln}" if idx == 0 else f"  {ln}" for idx, ln in enumerate(raw_lines)
            ]
        else:
            font, size, leading, width, x_pos, space_before, space_after = (
                "/F1",
                11,
                15,
                82,
                margin_x,
                0,
                8,
            )
            wrapped = textwrap.wrap(
                content, width=width, break_long_words=True, break_on_hyphens=False
            ) or [content]

        if space_before and pages[-1]:
            y -= space_before
        for line_text in wrapped:
            ensure_space(leading)
            y -= leading
            pages[-1].append((font, size, y, x_pos, line_text))
        y -= space_after

    # Build PDF 1.4 objects
    page_count = len(pages)
    # Object numbering:
    # 1: Catalog, 2: Pages, 3: Font F1 (Helvetica), 4: Font F2 (Helvetica-Bold), 5: Info
    # For page i (0..page_count-1):
    #   content_obj = 6 + 2*i
    #   page_obj    = 7 + 2*i
    page_obj_ids = [7 + 2 * i for i in range(page_count)]
    kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [ {kids_str} ] /Count {page_count} >>".encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        f"<< /Title ({_pdf_escape_string(doc_title or 'Casper Draft')}) /Producer (Casper) >>".encode(
            "ascii"
        ),
    ]

    for page_lines in pages:
        stream_cmds: list[str] = ["BT"]
        current_font = ""
        current_size = 0
        for font, size, ypos, xpos, line_text in page_lines:
            if font != current_font or size != current_size:
                stream_cmds.append(f"{font} {size} Tf")
                current_font = font
                current_size = size
            stream_cmds.append(f"1 0 0 1 {xpos} {ypos} Tm")
            stream_cmds.append(f"({_pdf_escape_string(line_text)}) Tj")
        stream_cmds.append("ET\n")
        stream_bytes = "\n".join(stream_cmds).encode("ascii")
        content_obj_id = len(objects) + 1
        objects.append(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("ascii")
            + stream_bytes
            + b"endstream"
        )
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {content_obj_id} 0 R >>"
            ).encode("ascii")
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for obj_num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    xref_offset = len(out)
    total_objs = len(objects) + 1
    out.extend(f"xref\n0 {total_objs}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {total_objs} /Root 1 0 R /Info 5 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def _export_json(
    text: str,
    doc_title: str | None,
    metadata: Mapping[str, Any] | None,
) -> bytes:
    bundle: dict[str, Any] = {
        "title": doc_title,
        "text": text,
    }
    if metadata:
        for k, v in metadata.items():
            key = str(k)
            if key not in {"title", "text"}:
                bundle[key] = v
    return (json.dumps(bundle, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def export_document(
    text: str,
    fmt: str,
    *,
    title: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[bytes, str, str]:
    """Export rendered draft text into a target format, returning (bytes, mime_type, filename)."""
    key = fmt.strip().lower()
    if key not in EXPORT_FORMATS:
        raise InputError(f"Unsupported export format: {fmt!r}")

    _label, ext, mime_type = EXPORT_FORMATS[key]
    elements = _parse_export_elements(text)

    explicit_title = title.strip() if title and title.strip() else None
    parsed_title = next((c for k, c in elements if k == "title"), None)
    effective_title = explicit_title or parsed_title
    if explicit_title and parsed_title is None:
        elements = [("title", explicit_title), *elements]

    filename = f"{_sanitize_slug(effective_title)}.{ext}"

    if key == "txt":
        payload = _export_txt(elements)
    elif key == "md":
        payload = _export_md(elements)
    elif key == "adoc":
        payload = _export_adoc(elements)
    elif key == "html":
        payload = _export_html(elements, effective_title)
    elif key == "pdf":
        payload = _export_pdf(elements, effective_title)
    elif key == "docx":
        payload = _export_docx(elements, effective_title)
    elif key == "odt":
        payload = _export_odt(elements)
    elif key == "rtf":
        payload = _export_rtf(elements)
    elif key == "tex":
        payload = _export_tex(elements, effective_title)
    elif key == "rst":
        payload = _export_rst(elements)
    elif key == "org":
        payload = _export_org(elements)
    else:
        payload = _export_json(text, effective_title, metadata)

    return payload, mime_type, filename
