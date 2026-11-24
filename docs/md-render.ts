/* Zero-dependency, CommonMark + GFM Markdown parser & safe DOM/HTML renderer for Casper Docs. */

declare const module: { exports?: unknown } | undefined;

type AlertType = "note" | "tip" | "important" | "warning" | "caution";
type TableAlign = "left" | "center" | "right" | null;

interface TocEntry {
  level: number;
  id: string;
  text: string;
}

type InlineNode =
  | { type: "text"; value: string }
  | { type: "code_span"; value: string }
  | { type: "softbreak" }
  | { type: "hardbreak" }
  | { type: "strong"; children: InlineNode[] }
  | { type: "em"; children: InlineNode[] }
  | { type: "del"; children: InlineNode[] }
  | { type: "link"; href: string; title: string; children: InlineNode[] }
  | { type: "image"; src: string; alt: string; title: string };

interface ListItemNode {
  checked: boolean | null;
  blocks: BlockNode[];
}

type BlockNode =
  | { type: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; id: string; text: string; children: InlineNode[] }
  | { type: "paragraph"; children: InlineNode[] }
  | { type: "code_block"; language: string; info: string; value: string }
  | { type: "hr" }
  | { type: "blockquote"; alertType: AlertType | null; blocks: BlockNode[] }
  | { type: "list"; ordered: boolean; start: number; items: ListItemNode[] }
  | { type: "table"; alignments: TableAlign[]; headers: InlineNode[][]; rows: InlineNode[][][] };

interface MarkdownAst {
  blocks: BlockNode[];
  toc: TocEntry[];
}

interface ResolvedLink {
  href: string;
  external?: boolean;
}

type LinkResolver = (href: string) => string | ResolvedLink;
type CopyCodeHandler = (code: string, button: HTMLButtonElement, language: string) => void;

interface RenderHtmlOptions {
  resolveLink?: LinkResolver;
}

interface RenderDomOptions {
  resolveLink?: LinkResolver;
  onCopyCode?: CopyCodeHandler;
}

interface RenderDomResult {
  toc: TocEntry[];
}

interface CasperMarkdownApi {
  parseMarkdown: (mdText: string) => MarkdownAst;
  renderAstToDom: (ast: MarkdownAst, doc: Document, options?: RenderDomOptions) => DocumentFragment;
  renderMarkdownToHtml: (mdText: string, options?: RenderHtmlOptions) => string;
  renderMarkdownToDom: (mdText: string, container: Element, options?: RenderDomOptions) => RenderDomResult;
}

interface ParseContext {
  toc: TocEntry[];
  slugCounts: Map<string, number>;
}

const ASCII_PUNCT_RE = /^[!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]$/;
const ALNUM_RE = /^[A-Za-z0-9]$/;
const UNSAFE_SCHEME_RE = /^(?:javascript|vbscript|data):/i;
const ALERT_RE = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:[ \t]+(.*))?$/i;

const ALERT_LABELS: Record<AlertType, string> = {
  note: "Note",
  tip: "Tip",
  important: "Important",
  warning: "Warning",
  caution: "Caution",
};

function sanitizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "#";
  const normalized = trimmed.replace(/[\u0000-\u001f\u007f\s]+/g, "");
  if (UNSAFE_SCHEME_RE.test(normalized)) {
    return "#";
  }
  return trimmed;
}

function resolveHref(rawHref: string, resolveLink?: LinkResolver): ResolvedLink {
  const safeInput = sanitizeUrl(rawHref);
  if (resolveLink) {
    const out = resolveLink(safeInput);
    if (typeof out === "string") {
      const safeOut = sanitizeUrl(out);
      return { href: safeOut, external: /^https?:/i.test(safeOut) };
    }
    const safeOut = sanitizeUrl(out.href);
    return {
      href: safeOut,
      external: out.external !== undefined ? out.external : /^https?:/i.test(safeOut),
    };
  }
  return { href: safeInput, external: /^https?:/i.test(safeInput) };
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function pushText(nodes: InlineNode[], value: string): void {
  if (!value) return;
  const prev = nodes[nodes.length - 1];
  if (prev && prev.type === "text") {
    prev.value += value;
  } else {
    nodes.push({ type: "text", value });
  }
}

function inlinePlainText(nodes: InlineNode[]): string {
  let out = "";
  for (const node of nodes) {
    if (node.type === "text" || node.type === "code_span") {
      out += node.value;
    } else if (node.type === "softbreak" || node.type === "hardbreak") {
      out += " ";
    } else if (node.type === "image") {
      out += node.alt;
    } else {
      out += inlinePlainText(node.children);
    }
  }
  return out;
}

function slugify(text: string, slugCounts: Map<string, number>): string {
  const base =
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s\-_]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "") || "section";
  const count = slugCounts.get(base) || 0;
  slugCounts.set(base, count + 1);
  return count === 0 ? base : `${base}-${count}`;
}

function findMatchingCodeSpanEnd(text: string, start: number, tickLen: number): number {
  let i = start;
  while (i < text.length) {
    if (text[i] === "`") {
      let run = 0;
      while (i + run < text.length && text[i + run] === "`") {
        run += 1;
      }
      if (run === tickLen) {
        return i;
      }
      i += run;
    } else {
      i += 1;
    }
  }
  return -1;
}

function unescapeBackslashes(text: string): string {
  let out = "";
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === "\\" && i + 1 < text.length && ASCII_PUNCT_RE.test(text[i + 1])) {
      out += text[i + 1];
      i += 1;
    } else {
      out += text[i];
    }
  }
  return out;
}

interface ParsedLinkResult {
  end: number;
  label: string;
  dest: string;
  title: string;
}

function parseLinkOrImage(text: string, start: number, isImage: boolean): ParsedLinkResult | null {
  const bracketStart = isImage ? start + 1 : start;
  if (text[bracketStart] !== "[") return null;

  let i = bracketStart + 1;
  let depth = 1;
  while (i < text.length && depth > 0) {
    const ch = text[i];
    if (ch === "\\" && i + 1 < text.length) {
      i += 2;
      continue;
    }
    if (ch === "`") {
      let ticks = 0;
      while (i + ticks < text.length && text[i + ticks] === "`") ticks += 1;
      const closeIdx = findMatchingCodeSpanEnd(text, i + ticks, ticks);
      if (closeIdx !== -1) {
        i = closeIdx + ticks;
        continue;
      }
      i += ticks;
      continue;
    }
    if (ch === "[") {
      depth += 1;
    } else if (ch === "]") {
      depth -= 1;
      if (depth === 0) break;
    }
    i += 1;
  }

  if (depth !== 0 || text[i] !== "]") return null;
  const label = text.slice(bracketStart + 1, i);
  if (text[i + 1] !== "(") return null;

  let j = i + 2;
  while (j < text.length && /[ \t\n]/.test(text[j])) j += 1;

  let dest = "";
  if (text[j] === "<") {
    j += 1;
    const destStart = j;
    while (j < text.length && text[j] !== ">" && text[j] !== "\n") {
      if (text[j] === "\\" && j + 1 < text.length) {
        j += 2;
      } else {
        j += 1;
      }
    }
    if (text[j] !== ">") return null;
    dest = unescapeBackslashes(text.slice(destStart, j));
    j += 1;
  } else {
    const destStart = j;
    let parenDepth = 0;
    while (j < text.length) {
      const ch = text[j];
      if (ch === "\\" && j + 1 < text.length) {
        j += 2;
        continue;
      }
      if (ch === "(") {
        parenDepth += 1;
        j += 1;
        continue;
      }
      if (ch === ")") {
        if (parenDepth === 0) break;
        parenDepth -= 1;
        j += 1;
        continue;
      }
      if (/[ \t\n]/.test(ch)) break;
      j += 1;
    }
    dest = unescapeBackslashes(text.slice(destStart, j));
  }

  while (j < text.length && /[ \t\n]/.test(text[j])) j += 1;

  let title = "";
  if (j < text.length && (text[j] === '"' || text[j] === "'" || text[j] === "(")) {
    const openQuote = text[j];
    const closeQuote = openQuote === "(" ? ")" : openQuote;
    j += 1;
    const titleStart = j;
    while (j < text.length && text[j] !== closeQuote) {
      if (text[j] === "\\" && j + 1 < text.length) {
        j += 2;
      } else {
        j += 1;
      }
    }
    if (text[j] !== closeQuote) return null;
    title = unescapeBackslashes(text.slice(titleStart, j));
    j += 1;
    while (j < text.length && /[ \t\n]/.test(text[j])) j += 1;
  }

  if (text[j] !== ")") return null;
  return { end: j + 1, label, dest, title };
}

function findDelimiterClose(text: string, start: number, markerChar: string, len: number): number {
  let i = start;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\" && i + 1 < text.length) {
      i += 2;
      continue;
    }
    if (ch === "`") {
      let ticks = 0;
      while (i + ticks < text.length && text[i + ticks] === "`") ticks += 1;
      const closeIdx = findMatchingCodeSpanEnd(text, i + ticks, ticks);
      if (closeIdx !== -1) {
        i = closeIdx + ticks;
        continue;
      }
      i += ticks;
      continue;
    }
    if (ch === "[" || (ch === "!" && text[i + 1] === "[")) {
      const linkRes = parseLinkOrImage(text, i, ch === "!");
      if (linkRes) {
        i = linkRes.end;
        continue;
      }
    }
    if (ch === markerChar) {
      let run = 0;
      while (i + run < text.length && text[i + run] === markerChar) run += 1;
      const prevChar = i > 0 ? text[i - 1] : "";
      const nextChar = i + run < text.length ? text[i + run] : "";
      const validNotSpaceBefore = prevChar !== "" && !/\s/.test(prevChar);
      const validUnderscoreAfter = markerChar !== "_" || !nextChar || !ALNUM_RE.test(nextChar);
      if (validNotSpaceBefore && validUnderscoreAfter && i > start) {
        if (run === len) {
          return i;
        }
        if (len === 2 && run === 3) {
          return i;
        }
        if (len === 1 && run === 3) {
          return i + 2;
        }
      }
      i += run;
      continue;
    }
    i += 1;
  }
  return -1;
}

function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = [];
  let i = 0;

  while (i < text.length) {
    const ch = text[i];

    // Hard break via two+ spaces before newline, or soft break
    if (ch === "\n") {
      const prev = nodes[nodes.length - 1];
      if (prev && prev.type === "text" && / {2,}$/.test(prev.value)) {
        prev.value = prev.value.replace(/ +$/, "");
        if (!prev.value) nodes.pop();
        nodes.push({ type: "hardbreak" });
      } else {
        nodes.push({ type: "softbreak" });
      }
      i += 1;
      continue;
    }

    // Backslash escape or backslash hard break
    if (ch === "\\" && i + 1 < text.length) {
      const next = text[i + 1];
      if (next === "\n") {
        nodes.push({ type: "hardbreak" });
        i += 2;
        continue;
      }
      if (ASCII_PUNCT_RE.test(next)) {
        pushText(nodes, next);
        i += 2;
        continue;
      }
      pushText(nodes, "\\");
      i += 1;
      continue;
    }

    // Code spans (single or multi-backtick, CommonMark §6.1)
    if (ch === "`") {
      let tickLen = 0;
      while (i + tickLen < text.length && text[i + tickLen] === "`") {
        tickLen += 1;
      }
      const closeIdx = findMatchingCodeSpanEnd(text, i + tickLen, tickLen);
      if (closeIdx !== -1) {
        let content = text.slice(i + tickLen, closeIdx).replace(/\n/g, " ");
        if (
          content.length >= 2 &&
          content.startsWith(" ") &&
          content.endsWith(" ") &&
          /[^ ]/.test(content)
        ) {
          content = content.slice(1, -1);
        }
        nodes.push({ type: "code_span", value: content });
        i = closeIdx + tickLen;
        continue;
      }
      pushText(nodes, text.slice(i, i + tickLen));
      i += tickLen;
      continue;
    }

    // Autolinks <https://...>, <mailto:...>, <user@domain.tld>
    if (ch === "<") {
      const closeAngle = text.indexOf(">", i + 1);
      if (closeAngle !== -1) {
        const inner = text.slice(i + 1, closeAngle);
        if (/^(?:https?:\/\/|mailto:)[^\s<>]+$/i.test(inner)) {
          nodes.push({
            type: "link",
            href: inner,
            title: "",
            children: [{ type: "text", value: inner }],
          });
          i = closeAngle + 1;
          continue;
        }
        if (/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/.test(inner)) {
          nodes.push({
            type: "link",
            href: `mailto:${inner}`,
            title: "",
            children: [{ type: "text", value: inner }],
          });
          i = closeAngle + 1;
          continue;
        }
      }
    }

    // Images ![alt](src "title")
    if (ch === "!" && text[i + 1] === "[") {
      const parsed = parseLinkOrImage(text, i, true);
      if (parsed) {
        const altText = inlinePlainText(parseInline(parsed.label));
        nodes.push({
          type: "image",
          src: parsed.dest,
          alt: altText,
          title: parsed.title,
        });
        i = parsed.end;
        continue;
      }
    }

    // Links [label](url "title")
    if (ch === "[") {
      const parsed = parseLinkOrImage(text, i, false);
      if (parsed) {
        nodes.push({
          type: "link",
          href: parsed.dest,
          title: parsed.title,
          children: parseInline(parsed.label),
        });
        i = parsed.end;
        continue;
      }
    }

    // Strikethrough ~~text~~
    if (ch === "~" && text[i + 1] === "~" && text[i + 2] && !/\s/.test(text[i + 2])) {
      const closeIdx = findDelimiterClose(text, i + 2, "~", 2);
      if (closeIdx !== -1) {
        const inner = text.slice(i + 2, closeIdx);
        nodes.push({ type: "del", children: parseInline(inner) });
        i = closeIdx + 2;
        continue;
      }
    }

    // Emphasis / Strong: ***, **, *, ___, __, _
    if (ch === "*" || ch === "_") {
      const prevChar = i > 0 ? text[i - 1] : "";
      const allowOpenUnderscore = ch !== "_" || !prevChar || !ALNUM_RE.test(prevChar);
      let run = 0;
      while (i + run < text.length && text[i + run] === ch) run += 1;

      if (allowOpenUnderscore && run <= 3) {
        let matched = false;
        const tryLengths = run === 3 ? [3, 2, 1] : run === 2 ? [2, 1] : [1];
        for (const len of tryLengths) {
          const nextAfterOpen = text[i + len];
          if (!nextAfterOpen || /\s/.test(nextAfterOpen)) continue;
          const closeIdx = findDelimiterClose(text, i + len, ch, len);
          if (closeIdx !== -1) {
            const inner = text.slice(i + len, closeIdx);
            const children = parseInline(inner);
            if (len === 3) {
              nodes.push({ type: "strong", children: [{ type: "em", children }] });
            } else if (len === 2) {
              nodes.push({ type: "strong", children });
            } else {
              nodes.push({ type: "em", children });
            }
            i = closeIdx + len;
            matched = true;
            break;
          }
        }
        if (matched) continue;
      }

      pushText(nodes, text.slice(i, i + run));
      i += run;
      continue;
    }

    pushText(nodes, ch);
    i += 1;
  }

  return nodes;
}

interface FenceOpen {
  indent: number;
  char: "`" | "~";
  len: number;
  info: string;
  language: string;
}

function matchFenceOpen(line: string): FenceOpen | null {
  const m = line.match(/^( {0,3})(`{3,}|~{3,})(.*)$/);
  if (!m) return null;
  const char = m[2][0] as "`" | "~";
  const info = m[3].trim();
  if (char === "`" && info.includes("`")) return null;
  const language = info ? info.split(/\s+/)[0] : "";
  return { indent: m[1].length, char, len: m[2].length, info, language };
}

function isFenceClose(line: string, char: "`" | "~", minLen: number): boolean {
  const m = line.match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);
  return Boolean(m && m[1][0] === char && m[1].length >= minLen);
}

function isHorizontalRule(line: string): boolean {
  return /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/.test(line);
}

function matchAtxHeading(line: string): { level: 1 | 2 | 3 | 4 | 5 | 6; content: string } | null {
  const m = line.match(/^ {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$/);
  if (!m) return null;
  const level = m[1].length as 1 | 2 | 3 | 4 | 5 | 6;
  const raw = (m[2] || "").replace(/[ \t]+#+[ \t]*$/, "").trim();
  return { level, content: raw };
}

function matchSetextUnderline(line: string): 1 | 2 | null {
  const m = line.match(/^ {0,3}(=+|-+)[ \t]*$/);
  if (!m) return null;
  return m[1][0] === "=" ? 1 : 2;
}

function splitTableCells(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !/(?:^|[^\\])(?:\\\\)*\\\|$/.test(s)) {
    s = s.slice(0, -1);
  }
  const cells: string[] = [];
  let cur = "";
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === "\\" && i + 1 < s.length && s[i + 1] === "|") {
      cur += "|";
      i += 2;
      continue;
    }
    if (ch === "`") {
      let ticks = 0;
      while (i + ticks < s.length && s[i + ticks] === "`") ticks += 1;
      const closeIdx = findMatchingCodeSpanEnd(s, i + ticks, ticks);
      if (closeIdx !== -1) {
        cur += s.slice(i, closeIdx + ticks);
        i = closeIdx + ticks;
        continue;
      }
      cur += s.slice(i, i + ticks);
      i += ticks;
      continue;
    }
    if (ch === "|") {
      cells.push(cur.trim());
      cur = "";
      i += 1;
      continue;
    }
    cur += ch;
    i += 1;
  }
  cells.push(cur.trim());
  return cells;
}

function parseTableSeparator(line: string): TableAlign[] | null {
  if (!line.includes("|") && !/^\s*:?-+:?\s*$/.test(line)) return null;
  const cells = splitTableCells(line);
  if (cells.length === 0) return null;
  const alignments: TableAlign[] = [];
  for (const cell of cells) {
    if (!/^:?-+:?$/.test(cell)) return null;
    const left = cell.startsWith(":");
    const right = cell.endsWith(":");
    if (left && right) {
      alignments.push("center");
    } else if (right) {
      alignments.push("right");
    } else if (left) {
      alignments.push("left");
    } else {
      alignments.push(null);
    }
  }
  return alignments;
}

function isTableStart(lines: string[], idx: number): boolean {
  if (idx + 1 >= lines.length) return false;
  const headerLine = lines[idx];
  const sepLine = lines[idx + 1];
  if (!headerLine.includes("|")) return false;
  const alignments = parseTableSeparator(sepLine);
  if (!alignments) return false;
  const headerCells = splitTableCells(headerLine);
  return headerCells.length === alignments.length && headerCells.length > 0;
}

interface ListMarker {
  indent: number;
  ordered: boolean;
  delimiter: string;
  start: number;
  contentIndent: number;
  rest: string;
}

function matchListMarker(line: string): ListMarker | null {
  if (isHorizontalRule(line)) return null;
  const uMatch = line.match(/^( {0,3})([-*+])(?:([ \t]+)(.*)|$)/);
  if (uMatch) {
    const indent = uMatch[1].length;
    const spaces = uMatch[3] ? uMatch[3].length : 1;
    return {
      indent,
      ordered: false,
      delimiter: uMatch[2],
      start: 1,
      contentIndent: indent + 1 + Math.min(spaces, 4),
      rest: uMatch[4] || "",
    };
  }
  const oMatch = line.match(/^( {0,3})(\d{1,9})([.)])(?:([ \t]+)(.*)|$)/);
  if (oMatch) {
    const indent = oMatch[1].length;
    const numStr = oMatch[2];
    const spaces = oMatch[4] ? oMatch[4].length : 1;
    return {
      indent,
      ordered: true,
      delimiter: oMatch[3],
      start: parseInt(numStr, 10),
      contentIndent: indent + numStr.length + 1 + Math.min(spaces, 4),
      rest: oMatch[5] || "",
    };
  }
  return null;
}

function stripIndent(line: string, maxSpaces: number): string {
  let removed = 0;
  let idx = 0;
  while (idx < line.length && removed < maxSpaces) {
    if (line[idx] === " ") {
      removed += 1;
      idx += 1;
    } else if (line[idx] === "\t") {
      removed += 4;
      idx += 1;
    } else {
      break;
    }
  }
  return line.slice(idx);
}

function leadingSpaces(line: string): number {
  let count = 0;
  for (let i = 0; i < line.length; i += 1) {
    if (line[i] === " ") count += 1;
    else if (line[i] === "\t") count += 4;
    else break;
  }
  return count;
}

function interruptsParagraph(lines: string[], idx: number): boolean {
  const line = lines[idx];
  if (!line.trim()) return true;
  if (matchFenceOpen(line)) return true;
  if (matchAtxHeading(line)) return true;
  if (/^ {0,3}>/.test(line)) return true;
  if (isHorizontalRule(line)) return true;
  if (isTableStart(lines, idx)) return true;
  if (matchListMarker(line)) return true;
  return false;
}

function parseBlocks(lines: string[], ctx: ParseContext): BlockNode[] {
  const blocks: BlockNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }

    // 1. Fenced code block (``` or ~~~)
    const fence = matchFenceOpen(line);
    if (fence) {
      const codeLines: string[] = [];
      i += 1;
      while (i < lines.length && !isFenceClose(lines[i], fence.char, fence.len)) {
        codeLines.push(fence.indent > 0 ? stripIndent(lines[i], fence.indent) : lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      blocks.push({
        type: "code_block",
        language: fence.language,
        info: fence.info,
        value: codeLines.join("\n"),
      });
      continue;
    }

    // 2. ATX heading (#..######)
    const atx = matchAtxHeading(line);
    if (atx) {
      const children = parseInline(atx.content);
      const plain = inlinePlainText(children).trim();
      const id = slugify(plain, ctx.slugCounts);
      ctx.toc.push({ level: atx.level, id, text: plain });
      blocks.push({ type: "heading", level: atx.level, id, text: plain, children });
      i += 1;
      continue;
    }

    // 3. Horizontal rule (standalone, not Setext underline)
    if (isHorizontalRule(line)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    // 4. Blockquote & GitHub Alerts
    if (/^ {0,3}>/.test(line)) {
      const qLines: string[] = [];
      while (i < lines.length && /^ {0,3}>/.test(lines[i])) {
        qLines.push(lines[i].replace(/^ {0,3}> ?/, ""));
        i += 1;
      }
      let alertType: AlertType | null = null;
      const firstNonEmpty = qLines.findIndex((l) => l.trim().length > 0);
      if (firstNonEmpty !== -1) {
        const alertMatch = qLines[firstNonEmpty].trim().match(ALERT_RE);
        if (alertMatch) {
          alertType = alertMatch[1].toLowerCase() as AlertType;
          const remainder = (alertMatch[2] || "").trim();
          if (remainder) {
            qLines[firstNonEmpty] = remainder;
          } else {
            qLines.splice(firstNonEmpty, 1);
          }
        }
      }
      const innerBlocks = parseBlocks(qLines, ctx);
      blocks.push({ type: "blockquote", alertType, blocks: innerBlocks });
      continue;
    }

    // 5. GFM Table
    if (isTableStart(lines, i)) {
      const alignments = parseTableSeparator(lines[i + 1]) as TableAlign[];
      const headers = splitTableCells(lines[i]).map((cell) => parseInline(cell));
      const rows: InlineNode[][][] = [];
      i += 2;
      while (
        i < lines.length &&
        lines[i].trim() &&
        lines[i].includes("|") &&
        !matchFenceOpen(lines[i]) &&
        !matchAtxHeading(lines[i]) &&
        !/^ {0,3}>/.test(lines[i]) &&
        !isHorizontalRule(lines[i])
      ) {
        const rawCells = splitTableCells(lines[i]);
        const rowCells: InlineNode[][] = [];
        for (let c = 0; c < alignments.length; c += 1) {
          rowCells.push(parseInline(rawCells[c] || ""));
        }
        rows.push(rowCells);
        i += 1;
      }
      blocks.push({ type: "table", alignments, headers, rows });
      continue;
    }

    // 6. Ordered / Unordered / Task Lists (with arbitrary nesting)
    const firstMarker = matchListMarker(line);
    if (firstMarker) {
      const listOrdered = firstMarker.ordered;
      const listDelimiter = firstMarker.delimiter;
      const listStart = firstMarker.start;
      const baseIndent = firstMarker.indent;
      const items: ListItemNode[] = [];

      while (i < lines.length) {
        const curMarker = matchListMarker(lines[i]);
        if (
          !curMarker ||
          curMarker.ordered !== listOrdered ||
          curMarker.delimiter !== listDelimiter ||
          curMarker.indent !== baseIndent
        ) {
          break;
        }

        const itemLines: string[] = [curMarker.rest];
        const minSubIndent = curMarker.contentIndent;
        i += 1;

        while (i < lines.length) {
          const nextLine = lines[i];
          if (!nextLine.trim()) {
            // Blank line continues item only if followed by indented content
            let look = i + 1;
            while (look < lines.length && !lines[look].trim()) look += 1;
            if (look < lines.length && leadingSpaces(lines[look]) >= minSubIndent) {
              itemLines.push("");
              i += 1;
              continue;
            }
            // Or if followed by another item in the same list, end this item and skip blank lines
            if (look < lines.length) {
              const afterBlank = matchListMarker(lines[look]);
              if (
                afterBlank &&
                afterBlank.ordered === listOrdered &&
                afterBlank.delimiter === listDelimiter &&
                afterBlank.indent === baseIndent
              ) {
                i = look;
                break;
              }
            }
            break;
          }

          const sp = leadingSpaces(nextLine);
          if (sp >= minSubIndent) {
            itemLines.push(stripIndent(nextLine, minSubIndent));
            i += 1;
            continue;
          }

          // Check if next line is another item at same list level or another block
          const sibling = matchListMarker(nextLine);
          if (sibling) {
            if (sibling.indent > baseIndent) {
              // Nested list indented slightly less than contentIndent (e.g. 2 spaces)
              itemLines.push(stripIndent(nextLine, Math.min(sp, minSubIndent)));
              i += 1;
              continue;
            }
            break;
          }

          if (interruptsParagraph(lines, i)) {
            break;
          }

          // Lazy continuation line inside list item
          itemLines.push(nextLine.trim());
          i += 1;
        }

        let checked: boolean | null = null;
        if (itemLines.length > 0) {
          const taskMatch = itemLines[0].match(/^\[([ xX])\](?:[ \t]+(.*)|$)/);
          if (taskMatch) {
            checked = taskMatch[1].toLowerCase() === "x";
            itemLines[0] = taskMatch[2] || "";
          }
        }

        const itemBlocks = parseBlocks(itemLines, ctx);
        items.push({ checked, blocks: itemBlocks });
      }

      blocks.push({
        type: "list",
        ordered: listOrdered,
        start: listStart,
        items,
      });
      continue;
    }

    // 7. Paragraph or Setext Heading (=== / ---)
    const pLines: string[] = [];
    let setextLevel: 1 | 2 | null = null;

    while (i < lines.length) {
      const cur = lines[i];
      if (!cur.trim()) break;
      if (pLines.length > 0) {
        const underline = matchSetextUnderline(cur);
        if (underline !== null) {
          setextLevel = underline;
          i += 1;
          break;
        }
        if (interruptsParagraph(lines, i)) {
          break;
        }
      }
      pLines.push(cur.replace(/^ {0,3}/, ""));
      i += 1;
    }

    if (setextLevel !== null) {
      const headingRaw = pLines.join("\n").trim();
      const children = parseInline(headingRaw);
      const plain = inlinePlainText(children).trim();
      const id = slugify(plain, ctx.slugCounts);
      ctx.toc.push({ level: setextLevel, id, text: plain });
      blocks.push({ type: "heading", level: setextLevel, id, text: plain, children });
    } else if (pLines.length > 0) {
      blocks.push({ type: "paragraph", children: parseInline(pLines.join("\n")) });
    } else {
      i += 1;
    }
  }

  return blocks;
}

function parseMarkdown(mdText: string): MarkdownAst {
  const normalized = String(mdText || "").replace(/\r\n?/g, "\n");
  const ctx: ParseContext = { toc: [], slugCounts: new Map<string, number>() };
  const blocks = parseBlocks(normalized.split("\n"), ctx);
  return { blocks, toc: ctx.toc };
}

function renderInlinesToHtml(nodes: InlineNode[], options?: RenderHtmlOptions): string {
  let html = "";
  for (const node of nodes) {
    switch (node.type) {
      case "text":
        html += escapeHtml(node.value);
        break;
      case "code_span":
        html += `<code>${escapeHtml(node.value)}</code>`;
        break;
      case "softbreak":
        html += "\n";
        break;
      case "hardbreak":
        html += "<br>\n";
        break;
      case "strong":
        html += `<strong>${renderInlinesToHtml(node.children, options)}</strong>`;
        break;
      case "em":
        html += `<em>${renderInlinesToHtml(node.children, options)}</em>`;
        break;
      case "del":
        html += `<del>${renderInlinesToHtml(node.children, options)}</del>`;
        break;
      case "link": {
        const resolved = resolveHref(node.href, options?.resolveLink);
        const titleAttr = node.title ? ` title="${escapeHtml(node.title)}"` : "";
        const extAttr = resolved.external ? ` target="_blank" rel="noopener"` : "";
        html += `<a href="${escapeHtml(resolved.href)}"${titleAttr}${extAttr}>${renderInlinesToHtml(node.children, options)}</a>`;
        break;
      }
      case "image": {
        const safeSrc = sanitizeUrl(node.src);
        const titleAttr = node.title ? ` title="${escapeHtml(node.title)}"` : "";
        html += `<img src="${escapeHtml(safeSrc)}" alt="${escapeHtml(node.alt)}"${titleAttr}>`;
        break;
      }
    }
  }
  return html;
}

function renderListItemToHtml(item: ListItemNode, options?: RenderHtmlOptions): string {
  const checkbox =
    item.checked === null
      ? ""
      : `<input type="checkbox" disabled${item.checked ? " checked" : ""}> `;
  const cls = item.checked === null ? "" : ` class="task-list-item"`;

  if (item.blocks.length === 0) {
    return `<li${cls}>${checkbox}</li>`;
  }
  if (item.blocks.length === 1 && item.blocks[0].type === "paragraph") {
    return `<li${cls}>${checkbox}${renderInlinesToHtml(item.blocks[0].children, options)}</li>`;
  }
  if (
    item.blocks.length >= 2 &&
    item.blocks[0].type === "paragraph" &&
    item.blocks.slice(1).every((b) => b.type === "list")
  ) {
    const first = renderInlinesToHtml(item.blocks[0].children, options);
    const rest = renderBlocksToHtml(item.blocks.slice(1), options);
    return `<li${cls}>${checkbox}${first}\n${rest}</li>`;
  }
  return `<li${cls}>${checkbox}${renderBlocksToHtml(item.blocks, options)}</li>`;
}

function renderBlocksToHtml(blocks: BlockNode[], options?: RenderHtmlOptions): string {
  const parts: string[] = [];
  for (const block of blocks) {
    switch (block.type) {
      case "heading": {
        const tag = `h${block.level}`;
        parts.push(
          `<${tag} id="${escapeHtml(block.id)}">${renderInlinesToHtml(block.children, options)}</${tag}>`
        );
        break;
      }
      case "paragraph":
        parts.push(`<p>${renderInlinesToHtml(block.children, options)}</p>`);
        break;
      case "code_block": {
        const langAttr = block.language ? ` class="language-${escapeHtml(block.language)}"` : "";
        parts.push(`<pre><code${langAttr}>${escapeHtml(block.value)}</code></pre>`);
        break;
      }
      case "hr":
        parts.push("<hr>");
        break;
      case "blockquote": {
        if (block.alertType) {
          const label = ALERT_LABELS[block.alertType];
          const inner = renderBlocksToHtml(block.blocks, options);
          parts.push(
            `<blockquote class="md-alert md-alert-${block.alertType}"><p class="md-alert-title">${escapeHtml(label)}</p>${inner ? "\n" + inner : ""}</blockquote>`
          );
        } else {
          parts.push(`<blockquote>\n${renderBlocksToHtml(block.blocks, options)}\n</blockquote>`);
        }
        break;
      }
      case "list": {
        const tag = block.ordered ? "ol" : "ul";
        const isTask = block.items.some((it) => it.checked !== null);
        const startAttr = block.ordered && block.start !== 1 ? ` start="${block.start}"` : "";
        const clsAttr = isTask ? ` class="task-list"` : "";
        const itemsHtml = block.items.map((it) => renderListItemToHtml(it, options)).join("\n");
        parts.push(`<${tag}${startAttr}${clsAttr}>\n${itemsHtml}\n</${tag}>`);
        break;
      }
      case "table": {
        const headCells = block.headers
          .map((cell, idx) => {
            const align = block.alignments[idx];
            const styleAttr = align ? ` style="text-align:${align}"` : "";
            return `<th${styleAttr}>${renderInlinesToHtml(cell, options)}</th>`;
          })
          .join("");
        const bodyRows = block.rows
          .map((row) => {
            const tds = row
              .map((cell, idx) => {
                const align = block.alignments[idx];
                const styleAttr = align ? ` style="text-align:${align}"` : "";
                return `<td${styleAttr}>${renderInlinesToHtml(cell, options)}</td>`;
              })
              .join("");
            return `<tr>${tds}</tr>`;
          })
          .join("\n");
        parts.push(
          `<div class="table-wrap"><table><thead><tr>${headCells}</tr></thead><tbody>${bodyRows ? "\n" + bodyRows + "\n" : ""}</tbody></table></div>`
        );
        break;
      }
    }
  }
  return parts.join("\n");
}

function renderMarkdownToHtml(mdText: string, options?: RenderHtmlOptions): string {
  const ast = parseMarkdown(mdText);
  return renderBlocksToHtml(ast.blocks, options);
}

function appendInlinesToDom(
  parent: Node,
  nodes: InlineNode[],
  doc: Document,
  options?: RenderDomOptions
): void {
  for (const node of nodes) {
    switch (node.type) {
      case "text":
        parent.appendChild(doc.createTextNode(node.value));
        break;
      case "code_span": {
        const code = doc.createElement("code");
        code.textContent = node.value;
        parent.appendChild(code);
        break;
      }
      case "softbreak":
        parent.appendChild(doc.createTextNode("\n"));
        break;
      case "hardbreak":
        parent.appendChild(doc.createElement("br"));
        break;
      case "strong": {
        const el = doc.createElement("strong");
        appendInlinesToDom(el, node.children, doc, options);
        parent.appendChild(el);
        break;
      }
      case "em": {
        const el = doc.createElement("em");
        appendInlinesToDom(el, node.children, doc, options);
        parent.appendChild(el);
        break;
      }
      case "del": {
        const el = doc.createElement("del");
        appendInlinesToDom(el, node.children, doc, options);
        parent.appendChild(el);
        break;
      }
      case "link": {
        const a = doc.createElement("a");
        const resolved = resolveHref(node.href, options?.resolveLink);
        a.setAttribute("href", resolved.href);
        if (node.title) a.setAttribute("title", node.title);
        if (resolved.external) {
          a.setAttribute("target", "_blank");
          a.setAttribute("rel", "noopener");
        }
        appendInlinesToDom(a, node.children, doc, options);
        parent.appendChild(a);
        break;
      }
      case "image": {
        const img = doc.createElement("img");
        img.setAttribute("src", sanitizeUrl(node.src));
        img.setAttribute("alt", node.alt);
        if (node.title) img.setAttribute("title", node.title);
        parent.appendChild(img);
        break;
      }
    }
  }
}

function appendBlocksToDom(
  parent: Node,
  blocks: BlockNode[],
  doc: Document,
  options?: RenderDomOptions
): void {
  for (const block of blocks) {
    switch (block.type) {
      case "heading": {
        const h = doc.createElement(`h${block.level}`);
        h.id = block.id;
        appendInlinesToDom(h, block.children, doc, options);
        parent.appendChild(h);
        break;
      }
      case "paragraph": {
        const p = doc.createElement("p");
        appendInlinesToDom(p, block.children, doc, options);
        parent.appendChild(p);
        break;
      }
      case "code_block": {
        const pre = doc.createElement("pre");
        const code = doc.createElement("code");
        if (block.language) {
          code.className = `language-${block.language}`;
        }
        code.textContent = block.value;
        pre.appendChild(code);

        if (options?.onCopyCode || block.language) {
          const wrap = doc.createElement("div");
          wrap.className = "md-code-block";
          const head = doc.createElement("div");
          head.className = "md-code-head recipe-head";
          const langBadge = doc.createElement("span");
          langBadge.className = "md-code-lang tag";
          langBadge.textContent = block.language || "text";
          head.appendChild(langBadge);
          if (options?.onCopyCode) {
            const copyHandler = options.onCopyCode;
            const btn = doc.createElement("button");
            btn.type = "button";
            btn.className = "md-code-copy copy-btn";
            btn.textContent = "Copy";
            btn.addEventListener("click", () => {
              copyHandler(block.value, btn, block.language);
            });
            head.appendChild(btn);
          }
          wrap.appendChild(head);
          wrap.appendChild(pre);
          parent.appendChild(wrap);
        } else {
          parent.appendChild(pre);
        }
        break;
      }
      case "hr":
        parent.appendChild(doc.createElement("hr"));
        break;
      case "blockquote": {
        const bq = doc.createElement("blockquote");
        if (block.alertType) {
          bq.className = `md-alert md-alert-${block.alertType}`;
          const titleEl = doc.createElement("p");
          titleEl.className = "md-alert-title";
          titleEl.textContent = ALERT_LABELS[block.alertType];
          bq.appendChild(titleEl);
        }
        appendBlocksToDom(bq, block.blocks, doc, options);
        parent.appendChild(bq);
        break;
      }
      case "list": {
        const listEl = doc.createElement(block.ordered ? "ol" : "ul");
        if (block.ordered && block.start !== 1) {
          listEl.setAttribute("start", String(block.start));
        }
        if (block.items.some((it) => it.checked !== null)) {
          listEl.className = "task-list";
        }
        for (const item of block.items) {
          const li = doc.createElement("li");
          if (item.checked !== null) {
            li.className = "task-list-item";
            const cb = doc.createElement("input");
            cb.type = "checkbox";
            cb.disabled = true;
            cb.setAttribute("disabled", "");
            if (item.checked) {
              cb.checked = true;
              cb.setAttribute("checked", "");
            }
            li.appendChild(cb);
            li.appendChild(doc.createTextNode(" "));
          }
          if (item.blocks.length === 1 && item.blocks[0].type === "paragraph") {
            appendInlinesToDom(li, item.blocks[0].children, doc, options);
          } else if (
            item.blocks.length >= 2 &&
            item.blocks[0].type === "paragraph" &&
            item.blocks.slice(1).every((b) => b.type === "list")
          ) {
            appendInlinesToDom(li, item.blocks[0].children, doc, options);
            appendBlocksToDom(li, item.blocks.slice(1), doc, options);
          } else {
            appendBlocksToDom(li, item.blocks, doc, options);
          }
          listEl.appendChild(li);
        }
        parent.appendChild(listEl);
        break;
      }
      case "table": {
        const wrap = doc.createElement("div");
        wrap.className = "table-wrap";
        const table = doc.createElement("table");
        const thead = doc.createElement("thead");
        const headRow = doc.createElement("tr");
        block.headers.forEach((cell, idx) => {
          const th = doc.createElement("th");
          const align = block.alignments[idx];
          if (align) th.style.textAlign = align;
          appendInlinesToDom(th, cell, doc, options);
          headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = doc.createElement("tbody");
        for (const row of block.rows) {
          const tr = doc.createElement("tr");
          row.forEach((cell, idx) => {
            const td = doc.createElement("td");
            const align = block.alignments[idx];
            if (align) td.style.textAlign = align;
            appendInlinesToDom(td, cell, doc, options);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        wrap.appendChild(table);
        parent.appendChild(wrap);
        break;
      }
    }
  }
}

function renderAstToDom(
  ast: MarkdownAst,
  doc: Document,
  options?: RenderDomOptions
): DocumentFragment {
  const frag = doc.createDocumentFragment();
  appendBlocksToDom(frag, ast.blocks, doc, options);
  return frag;
}

function renderMarkdownToDom(
  mdText: string,
  container: Element,
  options?: RenderDomOptions
): RenderDomResult {
  const ast = parseMarkdown(mdText);
  const doc = container.ownerDocument || document;
  const frag = renderAstToDom(ast, doc, options);
  if (typeof container.replaceChildren === "function") {
    container.replaceChildren(frag);
  } else {
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }
    container.appendChild(frag);
  }
  return { toc: ast.toc };
}

const CasperMarkdown: CasperMarkdownApi = {
  parseMarkdown,
  renderAstToDom,
  renderMarkdownToHtml,
  renderMarkdownToDom,
};

if (typeof module === "object" && module && typeof module.exports === "object") {
  module.exports = CasperMarkdown;
}

const globalScope = globalThis as { CasperMarkdown?: CasperMarkdownApi };
globalScope.CasperMarkdown = CasperMarkdown;
