/* Zero-dependency, strictly DOM/textContent Markdown renderer for Casper GitHub Pages. */
(function () {
  "use strict";

  const ALLOWED_DOC_RE = /^(?:using|data-model|api-reference|testing|CHECKPOINT)\.md$|^adr\/(?:README|TEMPLATE|[0-9]{4}-[a-z0-9-]+)\.md$/;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function resolveRelativeMd(baseFile, href) {
    if (/^(?:https?:|mailto:|#)/i.test(href)) {
      return { href: href, external: /^https?:/i.test(href) };
    }
    const parts = href.split("#");
    const relPath = parts[0];
    const hash = parts.length > 1 ? "#" + parts.slice(1).join("#") : "";
    const baseDir = baseFile.includes("/") ? baseFile.slice(0, baseFile.lastIndexOf("/") + 1) : "";
    const combined = (baseDir + relPath).split("/");
    const resolved = [];
    for (const seg of combined) {
      if (!seg || seg === ".") continue;
      if (seg === "..") {
        resolved.pop();
      } else {
        resolved.push(seg);
      }
    }
    const target = resolved.join("/");
    if (ALLOWED_DOC_RE.test(target)) {
      return { href: "doc.html?file=" + encodeURIComponent(target) + hash, external: false };
    }
    return { href: target + hash, external: false };
  }

  function appendInline(parent, text, baseFile) {
    // Tokenize inline code, links [label](url), bold **text**, italic *text*
    const tokenRe = /(`[^`]+`|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*)/g;
    let last = 0;
    let match;
    while ((match = tokenRe.exec(text)) !== null) {
      if (match.index > last) {
        parent.appendChild(document.createTextNode(text.slice(last, match.index)));
      }
      const tok = match[0];
      if (tok.startsWith("`") && tok.endsWith("`")) {
        parent.appendChild(el("code", "", tok.slice(1, -1)));
      } else if (tok.startsWith("[")) {
        const closeBracket = tok.indexOf("](");
        const label = tok.slice(1, closeBracket);
        const rawHref = tok.slice(closeBracket + 2, -1).trim();
        const link = document.createElement("a");
        const resolved = resolveRelativeMd(baseFile, rawHref);
        link.href = resolved.href;
        if (resolved.external) {
          link.target = "_blank";
          link.rel = "noopener";
        }
        link.textContent = label;
        parent.appendChild(link);
      } else if (tok.startsWith("**") && tok.endsWith("**")) {
        parent.appendChild(el("strong", "", tok.slice(2, -2)));
      } else if (tok.startsWith("*") && tok.endsWith("*")) {
        parent.appendChild(el("em", "", tok.slice(1, -1)));
      } else {
        parent.appendChild(document.createTextNode(tok));
      }
      last = tokenRe.lastIndex;
    }
    if (last < text.length) {
      parent.appendChild(document.createTextNode(text.slice(last)));
    }
  }

  function slugify(text) {
    return text
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-");
  }

  function parseTableRow(line) {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((c) => c.trim());
  }

  function isTableSeparator(line) {
    return /^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$/.test(line);
  }

  function renderMarkdown(mdText, container, baseFile) {
    container.replaceChildren();
    const lines = mdText.replace(/\r\n/g, "\n").split("\n");
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      if (!trimmed) {
        i += 1;
        continue;
      }

      // Fenced code block
      if (trimmed.startsWith("```")) {
        const codeLines = [];
        i += 1;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          codeLines.push(lines[i]);
          i += 1;
        }
        i += 1; // closing fence
        const pre = document.createElement("pre");
        pre.appendChild(el("code", "", codeLines.join("\n")));
        container.appendChild(pre);
        continue;
      }

      // Horizontal rule
      if (/^(?:---+|\*\*\*+|___+)$/.test(trimmed)) {
        container.appendChild(document.createElement("hr"));
        i += 1;
        continue;
      }

      // ATX headings
      const hMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
      if (hMatch) {
        const level = Math.min(hMatch[1].length, 6);
        const headingText = hMatch[2].replace(/\s+#+\s*$/, "");
        const h = document.createElement("h" + level);
        h.id = slugify(headingText);
        appendInline(h, headingText, baseFile);
        container.appendChild(h);
        if (level === 1) {
          document.title = headingText + " — Casper Docs";
        }
        i += 1;
        continue;
      }

      // GFM Table
      if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        const wrap = el("div", "table-wrap");
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        for (const cell of parseTableRow(lines[i])) {
          const th = document.createElement("th");
          appendInline(th, cell, baseFile);
          trHead.appendChild(th);
        }
        thead.appendChild(trHead);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
          const tr = document.createElement("tr");
          for (const cell of parseTableRow(lines[i])) {
            const td = document.createElement("td");
            appendInline(td, cell, baseFile);
            tr.appendChild(td);
          }
          tbody.appendChild(tr);
          i += 1;
        }
        table.appendChild(tbody);
        wrap.appendChild(table);
        container.appendChild(wrap);
        continue;
      }

      // Blockquote
      if (trimmed.startsWith(">")) {
        const qLines = [];
        while (i < lines.length && lines[i].trim().startsWith(">")) {
          qLines.push(lines[i].trim().replace(/^>\s?/, ""));
          i += 1;
        }
        const bq = document.createElement("blockquote");
        appendInline(bq, qLines.join(" "), baseFile);
        container.appendChild(bq);
        continue;
      }

      // Unordered list
      if (/^[-*+]\s+/.test(trimmed)) {
        const ul = document.createElement("ul");
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          const li = document.createElement("li");
          appendInline(li, lines[i].trim().replace(/^[-*+]\s+/, ""), baseFile);
          ul.appendChild(li);
          i += 1;
        }
        container.appendChild(ul);
        continue;
      }

      // Ordered list
      if (/^\d+[.)]\s+/.test(trimmed)) {
        const ol = document.createElement("ol");
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          const li = document.createElement("li");
          appendInline(li, lines[i].trim().replace(/^\d+[.)]\s+/, ""), baseFile);
          ol.appendChild(li);
          i += 1;
        }
        container.appendChild(ol);
        continue;
      }

      // Paragraph (join contiguous plain lines)
      const pLines = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !lines[i].trim().startsWith("#") &&
        !lines[i].trim().startsWith("```") &&
        !lines[i].trim().startsWith(">") &&
        !/^[-*+]\s+/.test(lines[i].trim()) &&
        !/^\d+[.)]\s+/.test(lines[i].trim())
      ) {
        pLines.push(lines[i].trim());
        i += 1;
      }
      const p = document.createElement("p");
      appendInline(p, pLines.join(" "), baseFile);
      container.appendChild(p);
    }
  }

  async function init() {
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("file") || "using.md").trim();
    const safeFile = ALLOWED_DOC_RE.test(requested) ? requested : "using.md";

    const renderedEl = document.getElementById("doc-rendered");
    const rawBox = document.getElementById("doc-raw");
    const rawCode = document.getElementById("doc-raw-code");
    const badge = document.getElementById("doc-path-badge");
    const openRaw = document.getElementById("btn-open-raw");
    const dlLink = document.getElementById("btn-download-md");
    const btnRendered = document.getElementById("btn-view-rendered");
    const btnRaw = document.getElementById("btn-view-raw");

    badge.textContent = "docs/" + safeFile;
    openRaw.href = safeFile;
    dlLink.href = safeFile;
    dlLink.setAttribute("download", safeFile.split("/").pop() || "document.md");

    function setMode(mode) {
      const showRaw = mode === "raw";
      renderedEl.classList.toggle("hidden", showRaw);
      rawBox.classList.toggle("hidden", !showRaw);
      btnRendered.classList.toggle("active", !showRaw);
      btnRaw.classList.toggle("active", showRaw);
    }

    btnRendered.addEventListener("click", function () {
      setMode("rendered");
    });
    btnRaw.addEventListener("click", function () {
      setMode("raw");
    });

    if (params.get("mode") === "raw") {
      setMode("raw");
    }

    let rawText = "";
    try {
      const resp = await fetch(safeFile);
      if (!resp.ok) {
        throw new Error("Could not load " + safeFile + " (HTTP " + resp.status + ")");
      }
      rawText = await resp.text();
      rawCode.textContent = rawText;
      renderMarkdown(rawText, renderedEl, safeFile);
    } catch (err) {
      renderedEl.replaceChildren(
        el("p", "", "Failed to load documentation: " + err.message)
      );
    }

    document.getElementById("btn-copy-raw").addEventListener("click", async function (e) {
      try {
        await navigator.clipboard.writeText(rawText);
        e.target.textContent = "Copied!";
        setTimeout(function () {
          e.target.textContent = "Copy Markdown";
        }, 1200);
      } catch (_err) {
        e.target.textContent = "Copy failed";
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
