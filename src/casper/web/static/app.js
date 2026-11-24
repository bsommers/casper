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

  function fillSelect(selectEl, items, labelFn, emptyLabel) {
    selectEl.replaceChildren();
    if (emptyLabel !== undefined) {
      const opt = el("option", "", emptyLabel);
      opt.value = "";
      selectEl.appendChild(opt);
    }
    for (const item of items) {
      const opt = el("option", "", labelFn(item));
      opt.value = typeof item === "string" ? item : item.id;
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

    // Provenance view ("Where each sentence came from")
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

    // Checks view
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

  async function init() {
    setupTabs();
    try {
      const [opts, statusRep] = await Promise.all([
        apiGet("/api/options"),
        apiGet("/api/backend-status"),
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

    document.getElementById("btn-download").addEventListener("click", function () {
      if (!state.lastResult) return;
      const blob = new Blob([state.lastResult.text || ""], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "casper-draft.txt";
      a.click();
      URL.revokeObjectURL(url);
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
