/* Casper localhost Web UI — frameworkless, CSP-safe, strictly textContent-only (TC-033). */
(function () {
  "use strict";

  const FACT_KINDS = [
    "status",
    "progress",
    "risk",
    "next_step",
    "decision",
    "background",
    "detail",
    "metric",
    "ask",
  ];

  const DEFAULT_EXPORT_FORMATS = [
    { id: "txt", label: "Plain Text (.txt)" },
    { id: "md", label: "Markdown (.md)" },
    { id: "adoc", label: "AsciiDoc (.adoc)" },
    { id: "html", label: "HTML5 Document (.html)" },
    { id: "pdf", label: "PDF Document (.pdf)" },
    { id: "docx", label: "Microsoft Word (.docx)" },
    { id: "odt", label: "OpenDocument Text (.odt)" },
    { id: "rtf", label: "Rich Text Format (.rtf)" },
    { id: "tex", label: "LaTeX (.tex)" },
    { id: "rst", label: "reStructuredText (.rst)" },
    { id: "org", label: "Emacs Org-mode (.org)" },
    { id: "json", label: "JSON Bundle (.json)" },
  ];

  const THEME_STORAGE_KEY = "casper_theme";

  const state = {
    options: null,
    factOverrides: {},
    lastResult: null,
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function showError(msg) {
    const banner = document.getElementById("global-error");
    if (!msg) {
      banner.textContent = "";
      banner.classList.add("hidden");
      return;
    }
    banner.textContent = msg;
    banner.classList.remove("hidden");
  }

  function getStoredTheme() {
    try {
      const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (saved === "light" || saved === "ghost") {
        return saved;
      }
    } catch (_) {
      // Ignore storage restrictions.
    }
    return "ghost";
  }

  function applyTheme(theme) {
    const resolved = theme === "light" ? "light" : "ghost";
    document.documentElement.setAttribute("data-theme", resolved);

    const logo = document.getElementById("brand-logo");
    if (logo) {
      logo.setAttribute(
        "src",
        resolved === "ghost"
          ? "/static/img/casper-logo-dark.svg"
          : "/static/img/casper-logo-light.svg"
      );
    }

    const btn = document.getElementById("btn-theme");
    if (btn) {
      btn.textContent = resolved === "ghost" ? "Theme: Ghostly" : "Theme: White";
      btn.setAttribute("aria-pressed", resolved === "light" ? "true" : "false");
    }

    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, resolved);
    } catch (_) {
      // Ignore storage restrictions.
    }
  }

  function setupThemeToggle() {
    applyTheme(getStoredTheme());
    const btn = document.getElementById("btn-theme");
    if (!btn) return;
    btn.addEventListener("click", function () {
      const current = document.documentElement.getAttribute("data-theme");
      applyTheme(current === "ghost" ? "light" : "ghost");
    });
  }

  async function apiGet(path) {
    const res = await fetch(path, { method: "GET" });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Request failed (" + res.status + ")");
    }
    return data;
  }

  async function apiPost(path, payload) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || "Request failed (" + res.status + ")");
    }
    return data;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000;
    const parts = [];
    for (let i = 0; i < bytes.length; i += chunkSize) {
      parts.push(String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize)));
    }
    return btoa(parts.join(""));
  }

  function countWords(text) {
    const trimmed = (text || "").trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }

  function parseDownloadFilename(headerValue, fallbackName) {
    if (!headerValue) return fallbackName;
    const utf8Match = /filename\*=UTF-8''([^;\s]+)/i.exec(headerValue);
    if (utf8Match && utf8Match[1]) {
      try {
        return decodeURIComponent(utf8Match[1].replace(/["']/g, ""));
      } catch (_) {
        return utf8Match[1];
      }
    }
    const basicMatch = /filename="?([^";\n]+)"?/i.exec(headerValue);
    if (basicMatch && basicMatch[1]) {
      return basicMatch[1].trim();
    }
    return fallbackName;
  }

  function fillSelect(selectEl, items, labelFn, emptyLabel) {
    selectEl.replaceChildren();
    if (emptyLabel !== undefined) {
      const opt = el("option", "", emptyLabel);
      opt.value = "";
      selectEl.appendChild(opt);
    }
    for (const item of items) {
      const opt = el("option", "", labelFn(item));
      opt.value = typeof item === "string" ? item : item.id || item.ext || item.format;
      selectEl.appendChild(opt);
    }
  }

  function syncModalityCompatibility() {
    if (!state.options) return;
    const structId = document.getElementById("w-structure").value;
    const structure = state.options.structures.find((s) => s.id === structId);
    const compatible = new Set(structure ? structure.compatible_modalities : []);
    const modSelect = document.getElementById("w-modality");
    let firstValid = null;
    for (const opt of modSelect.options) {
      const ok = compatible.size === 0 || compatible.has(opt.value);
      opt.disabled = !ok;
      if (ok && firstValid === null) {
        firstValid = opt.value;
      }
    }
    if (modSelect.selectedOptions[0] && modSelect.selectedOptions[0].disabled && firstValid) {
      modSelect.value = firstValid;
    }
  }

  function renderBackendBadges(statusReport) {
    const container = document.getElementById("backend-badges");
    container.replaceChildren();
    const backends = (statusReport && statusReport.backends) || {};
    for (const name of Object.keys(backends)) {
      const info = backends[name];
      const cls = info.available ? "chip ok" : "chip warn";
      const label = info.available
        ? name + ": ready" + (info.version ? " (" + info.version + ")" : "")
        : name + ": unavailable";
      container.appendChild(el("span", cls, label));
    }
  }

  function renderFactsInspector(facts) {
    const wrapper = document.getElementById("facts-inspector");
    const list = document.getElementById("facts-list");
    list.replaceChildren();
    state.factOverrides = {};

    for (const fact of facts) {
      const row = el("div", "fact-row");
      const textSpan = el("span", "fact-text", "[" + fact.id + "] " + fact.text);
      const kindSelect = el("select");
      for (const k of FACT_KINDS) {
        const opt = el("option", "", k);
        opt.value = k;
        if (k === fact.kind) {
          opt.selected = true;
        }
        kindSelect.appendChild(opt);
      }
      kindSelect.addEventListener("change", function () {
        if (kindSelect.value === fact.kind) {
          delete state.factOverrides[fact.id];
        } else {
          state.factOverrides[fact.id] = kindSelect.value;
        }
      });
      row.appendChild(textSpan);
      row.appendChild(kindSelect);
      list.appendChild(row);
    }
    wrapper.classList.remove("hidden");
  }

  function renderResult(data) {
    state.lastResult = data;
    document.getElementById("draft-output").textContent = data.text || "";
    document.getElementById("btn-copy").disabled = false;
    document.getElementById("btn-download").disabled = false;

    const chips = document.getElementById("result-chips");
    chips.replaceChildren();

    const val = data.validation;
    chips.appendChild(
      el("span", val.ok ? "chip ok" : "chip err", val.ok ? "Validation: PASS" : "Validation: FAIL")
    );
    chips.appendChild(
      el("span", "chip", "Persona: " + Math.round(val.persona_score) + "/100")
    );
    if (val.voice_report) {
      chips.appendChild(
        el(
          "span",
          "chip",
          "Voice: " + val.voice_report.overall.toFixed(1) + " (" + val.voice_report.band + ")"
        )
      );
    }
    if (data.backend) {
      chips.appendChild(el("span", "chip", "Backend: " + data.backend.used));
    }

    const provList = document.getElementById("provenance-list");
    provList.replaceChildren();
    for (const entry of data.fact_trace || []) {
      const row = el("div", "trace-row");
      row.appendChild(el("div", "", "[" + entry.section + "] " + entry.text));
      const srcLine = entry.frame
        ? "Closing frame (no facts cited)"
        : "Cited facts: " +
          (entry.facts || []).map((f) => f.id + " (" + f.kind + "): " + f.text).join(" | ");
      row.appendChild(el("div", "trace-sources", srcLine));
      provList.appendChild(row);
    }

    const checksList = document.getElementById("checks-list");
    checksList.replaceChildren();
    const findings = (val && val.findings) || [];
    if (findings.length === 0) {
      checksList.appendChild(el("div", "check-row", "All automated fidelity, persona, and limit checks passed."));
    } else {
      for (const f of findings) {
        const row = el("div", "check-row");
        const badgeCls = f.level === "error" ? "chip err" : "chip warn";
        row.appendChild(el("span", badgeCls, f.level.toUpperCase() + " " + f.code));
        row.appendChild(el("span", "", " " + f.message));
        checksList.appendChild(row);
      }
    }
  }

  function renderScoreReport(report) {
    const container = document.getElementById("score-result");
    const chips = document.getElementById("score-chips");
    chips.replaceChildren();
    chips.appendChild(el("span", "chip ok", "Overall: " + report.overall.toFixed(1) + "/100"));
    chips.appendChild(el("span", "chip", "Band: " + report.band));
    chips.appendChild(el("span", "chip", "Confidence: " + report.confidence));
    chips.appendChild(el("span", "chip", "Words: " + report.word_count));

    const dims = document.getElementById("score-dimensions");
    dims.replaceChildren();
    for (const key of Object.keys(report.dimensions || {})) {
      const val = report.dimensions[key];
      dims.appendChild(el("div", "dim-row", key + ": " + (val * 100).toFixed(1) + "%"));
    }

    const gaps = document.getElementById("score-gaps");
    gaps.replaceChildren();
    const gapList = report.largest_gaps || [];
    if (gapList.length === 0) {
      gaps.appendChild(el("div", "gap-row", "No major style gaps detected."));
    } else {
      for (const g of gapList) {
        gaps.appendChild(
          el("div", "gap-row", g.feature + " (" + g.score.toFixed(2) + "): " + g.explanation)
        );
      }
    }
    container.classList.remove("hidden");
  }

  function setupTabs() {
    const tabs = document.querySelectorAll(".tab");
    tabs.forEach((btn) => {
      btn.addEventListener("click", function () {
        tabs.forEach((b) => {
          b.classList.remove("active");
          b.setAttribute("aria-selected", "false");
        });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        const target = btn.getAttribute("data-tab");
        document.querySelectorAll(".panel").forEach((panel) => {
          panel.classList.toggle("hidden", panel.id !== "tab-" + target);
        });
      });
    });

    const subtabs = document.querySelectorAll(".subtab");
    subtabs.forEach((btn) => {
      btn.addEventListener("click", function () {
        subtabs.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const view = btn.getAttribute("data-view");
        document.querySelectorAll(".result-view").forEach((pane) => {
          pane.classList.toggle("hidden", pane.id !== "view-" + view);
        });
      });
    });
  }

  async function handleFileUpload(file, targetTextareaId, statusId, topicInputId) {
    if (!file) return;
    showError("");
    const statusEl = document.getElementById(statusId);
    statusEl.className = "upload-status chip";
    statusEl.textContent = "Loading " + file.name + "...";

    try {
      const buffer = await file.arrayBuffer();
      const b64 = arrayBufferToBase64(buffer);
      const data = await apiPost("/api/upload", {
        filename: file.name,
        content_base64: b64,
      });

      const text = data.text || "";
      document.getElementById(targetTextareaId).value = text;

      if (topicInputId && data.title) {
        const topicEl = document.getElementById(topicInputId);
        if (topicEl && !topicEl.value.trim()) {
          topicEl.value = data.title;
        }
      }

      const ext = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "txt";
      const fmt = data.format || ext;
      const words = typeof data.word_count === "number" ? data.word_count : countWords(text);
      statusEl.className = "upload-status chip ok";
      statusEl.textContent = "Loaded " + (data.filename || file.name) + " (" + fmt + ", " + words + " words)";
    } catch (err) {
      statusEl.className = "upload-status chip err";
      statusEl.textContent = "Upload failed";
      showError(err.message);
    }
  }

  function setupUploadZone(zoneId, inputId, targetTextareaId, statusId, topicInputId) {
    const zone = document.getElementById(zoneId);
    const input = document.getElementById(inputId);
    if (!zone || !input) return;

    input.addEventListener("change", function () {
      const file = input.files && input.files[0];
      if (file) {
        handleFileUpload(file, targetTextareaId, statusId, topicInputId);
        input.value = "";
      }
    });

    zone.addEventListener("dragover", function (ev) {
      ev.preventDefault();
      zone.classList.add("dragover");
    });

    zone.addEventListener("dragleave", function () {
      zone.classList.remove("dragover");
    });

    zone.addEventListener("drop", function (ev) {
      ev.preventDefault();
      zone.classList.remove("dragover");
      const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
      if (file) {
        handleFileUpload(file, targetTextareaId, statusId, topicInputId);
      }
    });
  }

  async function init() {
    setupThemeToggle();
    setupTabs();
    setupUploadZone("w-upload-zone", "w-file-upload", "w-notes", "w-upload-status", "w-topic");
    setupUploadZone("s-upload-zone", "s-file-upload", "s-text", "s-upload-status", null);

    try {
      const [opts, statusRep, formatsRep] = await Promise.all([
        apiGet("/api/options"),
        apiGet("/api/backend-status"),
        apiGet("/api/formats").catch(function () {
          return { export_formats: DEFAULT_EXPORT_FORMATS };
        }),
      ]);
      state.options = opts;

      fillSelect(document.getElementById("w-structure"), opts.structures, (s) => s.id);
      fillSelect(document.getElementById("w-modality"), opts.modalities, (m) => m.id + " (" + m.markup + ")");
      fillSelect(document.getElementById("w-source"), opts.personas.source, (p) => p.id);
      fillSelect(document.getElementById("w-target"), opts.personas.target, (p) => p.id);
      fillSelect(document.getElementById("w-author"), opts.authors, (a) => a.display_name + " (" + a.id + ")", "(none)");
      fillSelect(document.getElementById("w-backend"), opts.backends, (b) => b);
      fillSelect(document.getElementById("s-author"), opts.authors, (a) => a.display_name + " (" + a.id + ")");
      fillSelect(document.getElementById("s-overlay"), opts.modalities, (m) => m.id, "(none)");

      const exportSelect = document.getElementById("export-format");
      const exportFormats =
        (formatsRep && Array.isArray(formatsRep.export_formats) && formatsRep.export_formats.length > 0)
          ? formatsRep.export_formats
          : DEFAULT_EXPORT_FORMATS;
      fillSelect(exportSelect, exportFormats, function (f) {
        return typeof f === "string" ? f : f.label || f.ext || f.id;
      });
      if (exportSelect.querySelector('option[value="txt"]')) {
        exportSelect.value = "txt";
      }

      document.getElementById("w-structure").addEventListener("change", syncModalityCompatibility);
      syncModalityCompatibility();
      renderBackendBadges(statusRep);
    } catch (err) {
      showError(err.message);
    }

    document.getElementById("btn-extract").addEventListener("click", async function () {
      showError("");
      try {
        const notes = document.getElementById("w-notes").value;
        const data = await apiPost("/api/extract", { notes: notes });
        renderFactsInspector(data.facts || []);
      } catch (err) {
        showError(err.message);
      }
    });

    document.getElementById("btn-generate").addEventListener("click", async function () {
      showError("");
      try {
        const authorVal = document.getElementById("w-author").value || null;
        const topicVal = document.getElementById("w-topic").value.trim() || null;
        const seedVal = parseInt(document.getElementById("w-seed").value, 10) || 0;
        const payload = {
          structure: document.getElementById("w-structure").value,
          modality: document.getElementById("w-modality").value,
          source: document.getElementById("w-source").value,
          target: document.getElementById("w-target").value,
          author: authorVal,
          topic: topicVal,
          seed: seedVal,
          backend: document.getElementById("w-backend").value,
          notes: document.getElementById("w-notes").value,
        };
        if (Object.keys(state.factOverrides).length > 0) {
          payload.fact_overrides = state.factOverrides;
        }
        const data = await apiPost("/api/generate", payload);
        renderResult(data);
      } catch (err) {
        showError(err.message);
      }
    });

    document.getElementById("btn-copy").addEventListener("click", async function () {
      if (!state.lastResult) return;
      try {
        await navigator.clipboard.writeText(state.lastResult.text || "");
      } catch (err) {
        showError("Clipboard copy failed: " + err.message);
      }
    });

    document.getElementById("btn-download").addEventListener("click", async function () {
      if (!state.lastResult) return;
      showError("");
      const fmt = document.getElementById("export-format").value || "txt";
      const ext = fmt.replace(/^\./, "") || "txt";
      const topicVal = document.getElementById("w-topic").value.trim() || null;

      try {
        const res = await fetch("/api/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            format: fmt,
            text: state.lastResult.text || "",
            title: topicVal,
            facts: state.lastResult.facts || [],
            fact_trace: state.lastResult.fact_trace || [],
            validation: state.lastResult.validation || {},
            record: state.lastResult.record || {},
          }),
        });
        if (!res.ok) {
          let errMsg = "Export failed (" + res.status + ")";
          try {
            const errData = await res.json();
            if (errData && errData.error) {
              errMsg = errData.error;
            }
          } catch (_) {
            // Keep HTTP status fallback.
          }
          throw new Error(errMsg);
        }
        const blob = await res.blob();
        const filename = parseDownloadFilename(
          res.headers.get("Content-Disposition"),
          "casper-draft." + ext
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } catch (err) {
        showError(err.message);
      }
    });

    document.getElementById("btn-score").addEventListener("click", async function () {
      showError("");
      try {
        const raw = document.getElementById("s-raw").checked;
        const overlay = document.getElementById("s-overlay").value || null;
        const payload = {
          author: document.getElementById("s-author").value,
          text: document.getElementById("s-text").value,
          raw: raw,
          overlay: raw ? null : overlay,
        };
        const data = await apiPost("/api/score", payload);
        renderScoreReport(data.report);
      } catch (err) {
        showError(err.message);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
