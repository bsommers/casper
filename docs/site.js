/* Casper GitHub Pages interactive showcase — zero frameworks, strictly textContent-only. */
(function () {
  "use strict";

  const CAPABILITIES = [
    { cat: "Writing", title: "write_draft / casper write", surface: "Python · CLI · POST /api/generate", desc: "Generate a fact-grounded, voice-ranked, validated draft with complete fact trace and reproducibility record." },
    { cat: "Writing", title: "extract_facts / --dry-run", surface: "Python · CLI · POST /api/extract", desc: "Inspect extracted facts, inline [kind] tags, salience scores, and apply per-fact kind overrides before writing." },
    { cat: "Writing", title: "list_options / --list-options", surface: "Python · CLI · GET /api/options", desc: "Discover available personas, structures, compatible modalities, authors, and writer backends." },
    { cat: "Writing", title: "backend_status / --backend-status", surface: "Python · CLI · GET /api/backend-status", desc: "Probe readiness and versions of built-in rules plus optional claude and agy CLI writers." },
    { cat: "Authors", title: "score_draft / casper author score", surface: "Python · CLI · POST /api/score", desc: "Score any draft across 32 stability features, 60 function words, and heading structure against an author voice." },
    { cat: "Authors", title: "author_build / casper author build", surface: "Python · CLI", desc: "Analyze multi-format writing samples into a tamper-guarded YAML profile and mode-0600 private .local.yaml." },
    { cat: "Authors", title: "author_inspect / casper author inspect", surface: "Python · CLI", desc: "Inspect corpus stats, curated/local companion layers, and pinned-feature drift reports." },
    { cat: "Authors", title: "author_show / casper author show", surface: "Python · CLI", desc: "Print raw generated or 3-layer resolved author profile with optional modality overlays." },
    { cat: "Authors", title: "author_list / casper author list", surface: "Python · CLI · GET /api/options", desc: "List cataloged authors sorted deterministically with word and document counts." },
    { cat: "Authors", title: "author_diff / casper author diff", surface: "Python · CLI", desc: "Compare two author profiles across all 32 stability features ranked by normalized delta." },
    { cat: "Personas", title: "5 Source Personas", surface: "developer · tech_lead · product_owner · project_manager · analyst", desc: "Source-side vocabulary priorities, depth preferences, and domain cues." },
    { cat: "Personas", title: "5 Target Personas", surface: "management · executive · engineering · product_owner · customer", desc: "Audience depth caps (1/3/6), jargon simplification, avoid-lists, and section ordering." },
    { cat: "Structures", title: "status_update", surface: "slack · email · memo · plain", desc: "Status, Progress, Risks & Blockers, Next Steps, and explicit-ask-only Asks." },
    { cat: "Structures", title: "decision_memo", surface: "memo · email · article · plain", desc: "Context, Recommendation, Evidence, Risks, and Next Steps & Asks." },
    { cat: "Structures", title: "technical_article", surface: "article · memo · plain", desc: "Overview, Technical Details, Key Decisions, Limitations & Risks, and What Comes Next." },
    { cat: "Modalities", title: "5 Lossless Modalities", surface: "slack · email · memo · article (HTML5) · plain", desc: "Format-specific headings, bullets, and word/character limits without ever modifying grounded wording." },
    { cat: "Web API", title: "Hardened Localhost Server", surface: "127.0.0.1 only · CSP · Host/Origin/Sec-Fetch-Site", desc: "Pre-read 256 KiB cap, single-flight lock (503 on contention), zero external CDNs, textContent-only UI." },
  ];

  const BRAND_ASSETS = [
    // Logos & Marks
    { cat: "Logos", title: "Primary Ghost Mark", sub: "512×512 SVG · 512/1024 PNG", preview: "brand/casper-mark.svg", links: [["SVG", "brand/casper-mark.svg"], ["512 PNG", "brand/casper-mark-512.png"], ["1024 PNG", "brand/casper-mark-1024.png"]] },
    { cat: "Logos", title: "Horizontal Logo (Dark)", sub: "640×180 SVG", preview: "brand/casper-logo-dark.svg", links: [["SVG", "brand/casper-logo-dark.svg"]] },
    { cat: "Logos", title: "Horizontal Logo (Light)", sub: "640×180 SVG", preview: "brand/casper-logo-light.svg", lightBg: true, links: [["SVG", "brand/casper-logo-light.svg"]] },
    { cat: "Logos", title: "Hero Social Banner", sub: "1200×360 SVG & PNG", preview: "brand/casper-hero.svg", links: [["SVG", "brand/casper-hero.svg"], ["PNG", "brand/casper-hero.png"]] },
    { cat: "Logos", title: "App Icons & Favicons", sub: "16..1024 PNG · SVG · ICO", preview: "brand/icon-512x512.png", links: [["1024 PNG", "brand/icon-1024x1024.png"], ["512 PNG", "brand/icon-512x512.png"], ["ICO", "brand/favicon.ico"], ["SVG", "brand/favicon.svg"]] },

    // Subsystem Icons
    { cat: "Icons", title: "Voice Profile Icon", sub: "64×64 SVG", preview: "brand/icons/icon-voice.svg", links: [["SVG", "brand/icons/icon-voice.svg"]] },
    { cat: "Icons", title: "Fact Graph Icon", sub: "64×64 SVG", preview: "brand/icons/icon-facts.svg", links: [["SVG", "brand/icons/icon-facts.svg"]] },
    { cat: "Icons", title: "Structure Plan Icon", sub: "64×64 SVG", preview: "brand/icons/icon-plan.svg", links: [["SVG", "brand/icons/icon-plan.svg"]] },
    { cat: "Icons", title: "Fidelity Validator Icon", sub: "64×64 SVG", preview: "brand/icons/icon-validate.svg", links: [["SVG", "brand/icons/icon-validate.svg"]] },
    { cat: "Icons", title: "Modality Format Icon", sub: "64×64 SVG", preview: "brand/icons/icon-format.svg", links: [["SVG", "brand/icons/icon-format.svg"]] },
    { cat: "Icons", title: "CLI Writer Icon", sub: "64×64 SVG", preview: "brand/icons/icon-cli-writer.svg", links: [["SVG", "brand/icons/icon-cli-writer.svg"]] },

    // Die-Cut Stickers
    { cat: "Stickers", title: "Die-Cut Ghost Sticker", sub: "1500×1500 transparent RGBA + SVG cutline", preview: "brand/stickers/casper-sticker-diecut.png", links: [["1500 PNG", "brand/stickers/casper-sticker-diecut.png"], ["1024 PNG", "brand/stickers/casper-sticker-diecut-1024.png"], ["SVG Cutline", "brand/stickers/casper-sticker-diecut.svg"]] },
    { cat: "Stickers", title: "Wordmark Die-Cut Sticker", sub: "1800×1200 transparent RGBA + SVG cutline", preview: "brand/stickers/casper-sticker-wordmark-diecut.png", links: [["PNG", "brand/stickers/casper-sticker-wordmark-diecut.png"], ["SVG Cutline", "brand/stickers/casper-sticker-wordmark-diecut.svg"]] },
    { cat: "Stickers", title: "Print-Ready Sticker Sheet", sub: "US Letter 2550×3300 (300 DPI)", preview: "brand/stickers/casper-sticker-sheet.png", links: [["300 DPI PNG", "brand/stickers/casper-sticker-sheet.png"], ["SVG Sheet", "brand/stickers/casper-sticker-sheet.svg"]] },

    // Monitor Wallpapers (Dark & Light)
    { cat: "Monitors", wp: true, res: "1920x1080", title: "Full HD 16:9 Monitor", sub: "1920×1080 SVG & PNG" },
    { cat: "Monitors", wp: true, res: "2560x1080", title: "Ultrawide 21:9 Monitor", sub: "2560×1080 SVG & PNG" },
    { cat: "Monitors", wp: true, res: "2560x1440", title: "QHD 1440p Monitor", sub: "2560×1440 SVG & PNG" },
    { cat: "Monitors", wp: true, res: "3440x1440", title: "UWQHD 3440×1440", sub: "3440×1440 SVG & PNG" },
    { cat: "Monitors", wp: true, res: "3480x1440", title: "Super-Ultrawide 3480×1440", sub: "3480×1440 SVG & PNG" },

    // Phone Wallpapers (Dark & Light)
    { cat: "Phones", wp: true, res: "1170x2532", title: "Phone Portrait (1170×2532)", sub: "iPhone 13/14/15/16 SVG & PNG" },
    { cat: "Phones", wp: true, res: "1290x2796", title: "Phone Pro Max (1290×2796)", sub: "iPhone Pro Max SVG & PNG" },
    { cat: "Phones", wp: true, res: "1440x3120", title: "Android Flagship (1440×3120)", sub: "QHD+ Portrait SVG & PNG" },
  ];

  let expCat = "All";
  let expQuery = "";
  let brandCat = "All";
  let wpTheme = "dark";

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function resolveAsset(item) {
    if (!item.wp) return item;
    const base = "brand/wallpapers/casper-wallpaper-" + wpTheme + "-" + item.res;
    return {
      cat: item.cat,
      title: item.title + " (" + (wpTheme === "dark" ? "Dark" : "Light") + ")",
      sub: item.sub,
      preview: base + ".png",
      lightBg: wpTheme === "light",
      links: [
        ["PNG", base + ".png"],
        ["SVG", base + ".svg"],
      ],
    };
  }

  function renderExplorer() {
    const grid = document.getElementById("explorer-grid");
    grid.replaceChildren();
    const q = expQuery.trim().toLowerCase();
    const matches = CAPABILITIES.filter((c) => {
      const catOk = expCat === "All" || c.cat === expCat;
      const qOk =
        !q ||
        c.title.toLowerCase().includes(q) ||
        c.surface.toLowerCase().includes(q) ||
        c.desc.toLowerCase().includes(q) ||
        c.cat.toLowerCase().includes(q);
      return catOk && qOk;
    });
    if (matches.length === 0) {
      grid.appendChild(el("div", "hud-card exp-card", "No matching capabilities."));
      return;
    }
    for (const item of matches) {
      const card = el("article", "hud-card exp-card");
      const meta = el("div", "exp-meta");
      meta.appendChild(el("span", "tag", item.cat));
      meta.appendChild(el("span", "tag", item.surface));
      card.appendChild(meta);
      card.appendChild(el("h3", "", item.title));
      card.appendChild(el("p", "", item.desc));
      grid.appendChild(card);
    }
  }

  function openModal(asset) {
    const modal = document.getElementById("preview-modal");
    document.getElementById("modal-title").textContent = asset.title + " — " + asset.sub;
    const img = document.getElementById("modal-img");
    img.src = asset.preview;
    img.alt = asset.title;

    const links = document.getElementById("modal-links");
    links.replaceChildren();
    for (const [label, href] of asset.links) {
      const a = el("a", "dl-link", "Download " + label);
      a.href = href;
      a.setAttribute("download", "");
      links.appendChild(a);
    }
    modal.classList.remove("hidden");
  }

  function closeModal() {
    document.getElementById("preview-modal").classList.add("hidden");
  }

  function renderBrandGrid() {
    const grid = document.getElementById("brand-grid");
    grid.replaceChildren();
    const items = BRAND_ASSETS.filter((a) => brandCat === "All" || a.cat === brandCat).map(resolveAsset);
    for (const asset of items) {
      const card = el("article", "hud-card asset-card");
      const wrap = el("div", "asset-thumb-wrap" + (asset.lightBg ? " light-checker" : ""));
      const img = document.createElement("img");
      img.className = "asset-thumb";
      img.src = asset.preview;
      img.alt = asset.title;
      img.loading = "lazy";
      wrap.appendChild(img);
      wrap.addEventListener("click", function () {
        openModal(asset);
      });

      card.appendChild(wrap);
      card.appendChild(el("h3", "asset-title", asset.title));
      card.appendChild(el("p", "asset-sub", asset.sub));

      const linkBar = el("div", "asset-links");
      for (const [label, href] of asset.links) {
        const a = el("a", "dl-link", label);
        a.href = href;
        a.setAttribute("download", "");
        linkBar.appendChild(a);
      }
      card.appendChild(linkBar);
      grid.appendChild(card);
    }
  }

  function buildPills(containerId, categories, activeVal, onSelect) {
    const container = document.getElementById(containerId);
    container.replaceChildren();
    for (const cat of categories) {
      const btn = el("button", "pill" + (cat === activeVal ? " active" : ""), cat);
      btn.type = "button";
      btn.addEventListener("click", function () {
        onSelect(cat);
        for (const child of container.children) {
          child.classList.toggle("active", child.textContent === cat);
        }
      });
      container.appendChild(btn);
    }
  }

  function init() {
    buildPills(
      "explorer-pills",
      ["All", "Writing", "Authors", "Personas", "Structures", "Modalities", "Web API"],
      expCat,
      function (cat) {
        expCat = cat;
        renderExplorer();
      }
    );

    buildPills(
      "brand-pills",
      ["All", "Logos", "Icons", "Stickers", "Monitors", "Phones"],
      brandCat,
      function (cat) {
        brandCat = cat;
        renderBrandGrid();
      }
    );

    document.getElementById("explorer-search").addEventListener("input", function (e) {
      expQuery = e.target.value;
      renderExplorer();
    });

    document.querySelectorAll("[data-wp-theme]").forEach((btn) => {
      btn.addEventListener("click", function () {
        wpTheme = btn.getAttribute("data-wp-theme");
        document.querySelectorAll("[data-wp-theme]").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        renderBrandGrid();
      });
    });

    document.querySelectorAll(".copy-btn").forEach((btn) => {
      btn.addEventListener("click", async function () {
        const text = btn.getAttribute("data-copy") || "";
        try {
          await navigator.clipboard.writeText(text);
          const orig = btn.textContent;
          btn.textContent = "Copied!";
          setTimeout(function () {
            btn.textContent = orig;
          }, 1200);
        } catch (_err) {
          btn.textContent = "Copy failed";
        }
      });
    });

    document.getElementById("modal-close").addEventListener("click", closeModal);
    document.getElementById("modal-close-bg").addEventListener("click", closeModal);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeModal();
    });

    renderExplorer();
    renderBrandGrid();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
