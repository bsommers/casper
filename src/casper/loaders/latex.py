"""LaTeX document loader (Rank 2)."""

from __future__ import annotations

import re

from casper.documents import sha256_bytes
from casper.models import Block, BlockKind, Document

_TITLE_RE = re.compile(r"\\title\{([^}]*)\}")
_AUTHOR_RE = re.compile(r"\\author\{([^}]*)\}")
_SECTION_RE = re.compile(r"\\(sub)*section\*?\{([^}]*)\}")
_ITEM_RE = re.compile(r"^\\item\s*(.*)$")


def _strip_comments(text: str) -> str:
    out_lines: list[str] = []
    for line in text.splitlines():
        # Strip unescaped % comments
        cleaned = re.sub(r"(?<!\\)%.*$", "", line)
        out_lines.append(cleaned)
    return "\n".join(out_lines)


def _strip_macros(text: str) -> str:
    # Unwrap common formatting macros \textbf{X}, \emph{X}, \textit{X}, \texttt{X}
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = re.sub(r"\\(?:textbf|emph|textit|texttt|underline|textrm)\{([^{}]*)\}", r"\1", cur)
    cur = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", cur)
    cur = re.sub(r"\\url\{([^}]*)\}", r"\1", cur)
    cur = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?", "", cur)
    cur = cur.replace("{", "").replace("}", "")
    cur = cur.replace("``", '"').replace("''", '"').replace("---", "—").replace("--", "–")
    return re.sub(r"\s+", " ", cur).strip()


def parse_latex(data: bytes, source: str) -> Document:
    raw = _strip_comments(data.decode("utf-8", errors="replace"))
    m_title = _TITLE_RE.search(raw)
    title = _strip_macros(m_title.group(1)) if m_title else None
    m_author = _AUTHOR_RE.search(raw)
    authors = (
        tuple(a.strip() for a in _strip_macros(m_author.group(1)).split("\\and") if a.strip())
        if m_author
        else ()
    )

    body = raw
    begin_m = re.search(r"\\begin\{document\}", body)
    if begin_m:
        body = body[begin_m.end() :]
    end_m = re.search(r"\\end\{document\}", body)
    if end_m:
        body = body[: end_m.start()]

    blocks: list[Block] = []
    para_buf: list[str] = []
    in_quote = False
    in_list = False

    def flush_para() -> None:
        if not para_buf:
            return
        cleaned = _strip_macros(" ".join(para_buf))
        if cleaned:
            kind = BlockKind.QUOTE if in_quote else BlockKind.PARAGRAPH
            blocks.append(Block(kind=kind, text=cleaned))
        para_buf.clear()

    for line in body.splitlines():
        s = line.strip()
        if not s:
            flush_para()
            continue
        if s.startswith(r"\begin{quote}") or s.startswith(r"\begin{quotation}"):
            flush_para()
            in_quote = True
            continue
        if s.startswith(r"\end{quote}") or s.startswith(r"\end{quotation}"):
            flush_para()
            in_quote = False
            continue
        if s.startswith(r"\begin{itemize}") or s.startswith(r"\begin{enumerate}"):
            flush_para()
            in_list = True
            continue
        if s.startswith(r"\end{itemize}") or s.startswith(r"\end{enumerate}"):
            flush_para()
            in_list = False
            continue
        if s == r"\maketitle":
            continue

        sec_m = _SECTION_RE.match(s)
        if sec_m:
            flush_para()
            sub_prefix = sec_m.group(1) or ""
            level = 2 + (len(sub_prefix) // 3)
            htext = _strip_macros(sec_m.group(2))
            if htext:
                blocks.append(Block(kind=BlockKind.HEADING, text=htext, level=level))
            continue

        if in_list:
            item_m = _ITEM_RE.match(s)
            if item_m:
                flush_para()
                itext = _strip_macros(item_m.group(1))
                if itext:
                    blocks.append(Block(kind=BlockKind.LIST_ITEM, text=itext, level=1))
                continue

        para_buf.append(s)

    flush_para()

    return Document(
        source=source,
        format="latex",
        title=title,
        authors=authors,
        blocks=tuple(blocks),
        sha256=sha256_bytes(data),
    )
