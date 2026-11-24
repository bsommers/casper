/* Dynamic Markdown documentation viewer wired to CasperMarkdown (strict DOM/textContent). */
(function () {
  "use strict";

  const ALLOWED_DOC_RE =
    /^(?:using|data-model|api-reference|testing|CHECKPOINT)\.md$|^adr\/(?:README|TEMPLATE|[0-9]{4}-[a-z0-9-]+)\.md$/;

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

  function renderToc(tocNav, toc) {
    if (!tocNav) return false;
    if (!toc || toc.length < 2) {
      tocNav.classList.add("hidden");
      tocNav.replaceChildren();
      return false;
    }

    const title = el("h2", "doc-toc-title", "Contents");
    const list = el("ul", "doc-toc-list");

    for (const entry of toc) {
      const li = el("li", "doc-toc-lvl-" + Math.min(Math.max(entry.level, 1), 6));
      const a = document.createElement("a");
      a.setAttribute("href", "#" + entry.id);
      a.textContent = entry.text;
      li.appendChild(a);
      list.appendChild(li);
    }

    tocNav.replaceChildren(title, list);
    tocNav.classList.remove("hidden");
    return true;
  }

  async function copyToClipboard(text, button, defaultLabel) {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied!";
      setTimeout(function () {
        button.textContent = defaultLabel;
      }, 1200);
    } catch (_err) {
      button.textContent = "Copy failed";
      setTimeout(function () {
        button.textContent = defaultLabel;
      }, 1200);
    }
  }

  async function init() {
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("file") || "using.md").trim();
    const safeFile = ALLOWED_DOC_RE.test(requested) ? requested : "using.md";

    const renderedEl = document.getElementById("doc-rendered");
    const tocNav = document.getElementById("doc-toc");
    const rawBox = document.getElementById("doc-raw");
    const rawCode = document.getElementById("doc-raw-code");
    const badge = document.getElementById("doc-path-badge");
    const staticHtmlLink = document.getElementById("btn-static-html");
    const openRaw = document.getElementById("btn-open-raw");
    const dlLink = document.getElementById("btn-download-md");
    const btnRendered = document.getElementById("btn-view-rendered");
    const btnRaw = document.getElementById("btn-view-raw");

    badge.textContent = "docs/" + safeFile;
    if (staticHtmlLink) {
      staticHtmlLink.setAttribute("href", "rendered/" + safeFile.replace(/\.md$/, ".html"));
    }
    openRaw.setAttribute("href", safeFile);
    dlLink.setAttribute("href", safeFile);
    dlLink.setAttribute("download", safeFile.split("/").pop() || "document.md");

    let hasToc = false;

    function setMode(mode) {
      const showRaw = mode === "raw";
      renderedEl.classList.toggle("hidden", showRaw);
      rawBox.classList.toggle("hidden", !showRaw);
      if (tocNav) {
        tocNav.classList.toggle("hidden", showRaw || !hasToc);
      }
      btnRendered.classList.toggle("active", !showRaw);
      btnRaw.classList.toggle("active", showRaw);
    }

    btnRendered.addEventListener("click", function () {
      setMode("rendered");
    });
    btnRaw.addEventListener("click", function () {
      setMode("raw");
    });

    const initialRaw = params.get("mode") === "raw";
    if (initialRaw) {
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

      const renderer = window.CasperMarkdown;
      if (!renderer || typeof renderer.renderMarkdownToDom !== "function") {
        throw new Error("CasperMarkdown renderer not loaded");
      }

      const result = renderer.renderMarkdownToDom(rawText, renderedEl, {
        resolveLink: function (href) {
          return resolveRelativeMd(safeFile, href);
        },
        onCopyCode: function (code, button) {
          copyToClipboard(code, button, "Copy");
        },
      });

      hasToc = renderToc(tocNav, result.toc);
      if (initialRaw && tocNav) {
        tocNav.classList.add("hidden");
      }

      const h1 = result.toc.find(function (entry) {
        return entry.level === 1;
      });
      if (h1 && h1.text) {
        document.title = h1.text + " — Casper Docs";
      }

      if (window.location.hash && window.location.hash.length > 1) {
        const targetId = decodeURIComponent(window.location.hash.slice(1));
        const anchor = document.getElementById(targetId);
        if (anchor && typeof anchor.scrollIntoView === "function") {
          anchor.scrollIntoView();
        }
      }
    } catch (err) {
      renderedEl.replaceChildren(
        el("p", "", "Failed to load documentation: " + (err && err.message ? err.message : String(err)))
      );
    }

    document.getElementById("btn-copy-raw").addEventListener("click", function (e) {
      copyToClipboard(rawText, e.target, "Copy Markdown");
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
