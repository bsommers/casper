"""Smoke & unit tests for static Markdown-to-HTML docs pre-rendering and HTML hygiene."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
RENDERED_DIR = DOCS_DIR / "rendered"
BUILDER_SCRIPT = ROOT / "scripts" / "build_docs_html.py"


def _load_builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_docs_html", BUILDER_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_docs_html"] = mod
    spec.loader.exec_module(mod)
    return mod


class _VisibleTextExtractor(HTMLParser):
    """Collect visible text outside code/pre/script/style elements."""

    SKIP_TAGS = frozenset({"code", "pre", "script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.chunks.append(data)


class _LinkExtractor(HTMLParser):
    """Extract all href and src attribute values from an HTML file."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for attr, val in attrs:
            if attr in ("href", "src") and val:
                self.refs.append((attr, val))


def test_build_docs_html_check_exits_zero() -> None:
    proc = subprocess.run(
        [sys.executable, str(BUILDER_SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"--check failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    for rel in (
        "using.html",
        "data-model.html",
        "api-reference.html",
        "testing.html",
        "CHECKPOINT.html",
        "adr/README.html",
        "adr/0001-no-in-process-llm.html",
        "adr/0012-shared-rewrites-fidelity-brand.html",
    ):
        assert (RENDERED_DIR / rel).is_file(), f"Missing rendered doc: docs/rendered/{rel}"


def test_zero_unrendered_backticks_in_visible_html() -> None:
    html_files = [DOCS_DIR / "index.html", *sorted(RENDERED_DIR.rglob("*.html"))]
    assert len(html_files) >= 18
    offenders: list[str] = []
    for html_path in html_files:
        parser = _VisibleTextExtractor()
        parser.feed(html_path.read_text(encoding="utf-8"))
        visible = "".join(parser.chunks)
        if "`" in visible:
            idx = visible.index("`")
            snippet = visible[max(0, idx - 30) : idx + 30].replace("\n", " ")
            offenders.append(f"{html_path.relative_to(ROOT)}: ...{snippet}...")
    assert not offenders, f"Unrendered backticks found in visible HTML text: {offenders}"


def test_all_relative_links_in_html_resolve() -> None:
    html_files = [DOCS_DIR / "index.html", *sorted(RENDERED_DIR.rglob("*.html"))]
    broken: list[str] = []
    for html_path in html_files:
        parser = _LinkExtractor()
        parser.feed(html_path.read_text(encoding="utf-8"))
        for attr, raw_ref in parser.refs:
            ref = raw_ref.strip()
            if ref.startswith(("http://", "https://", "mailto:", "#", "javascript:", "data:")):
                continue
            path_part = ref.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            resolved = (html_path.parent / path_part).resolve()
            if not resolved.exists():
                broken.append(f"{html_path.relative_to(ROOT)} [{attr}={raw_ref}] -> {resolved}")
    assert not broken, f"Broken relative links in rendered/index HTML: {broken}"


def test_inline_code_and_escapes() -> None:
    mod = _load_builder()
    assert mod.render_inline("Use `casper <write>` now") == "Use <code>casper &lt;write&gt;</code> now"
    assert (
        mod.render_inline("Double ``code with `tick` inside`` span")
        == "Double <code>code with `tick` inside</code> span"
    )
    assert (
        mod.render_inline("Edge `` `tick` `` trim")
        == "Edge <code>`tick`</code> trim"
    )
    escaped = mod.render_inline(r"Literal \`tick\` and \*star\* and \|pipe\|")
    assert "<code>" not in escaped
    assert "<em>" not in escaped
    assert "Literal `tick` and *star* and |pipe|" == escaped


def test_emphasis_strikethrough_and_intraword_underscores() -> None:
    mod = _load_builder()
    out = mod.render_inline(
        "**bold** __bold2__ *italic* _italic2_ ***both*** ~~strike~~ status_update_v1"
    )
    assert "<strong>bold</strong>" in out
    assert "<strong>bold2</strong>" in out
    assert "<em>italic</em>" in out
    assert "<em>italic2</em>" in out
    assert "<strong><em>both</em></strong>" in out
    assert "<del>strike</del>" in out
    assert "status_update_v1" in out
    assert "<em>update</em>" not in out


def test_links_images_and_autolinks() -> None:
    mod = _load_builder()
    link_code = mod.render_inline("[`src/casper/models.py`](../src/casper/models.py)")
    assert link_code == '<a href="../src/casper/models.py"><code>src/casper/models.py</code></a>'

    link_bold = mod.render_inline("[**Casper Docs**](https://example.com/docs)")
    assert (
        link_bold
        == '<a href="https://example.com/docs" target="_blank" rel="noopener"><strong>Casper Docs</strong></a>'
    )

    img = mod.render_inline('![Ghost Mark](brand/casper-mark.svg "Mark")')
    assert '<img src="brand/casper-mark.svg" alt="Ghost Mark" title="Mark" loading="lazy">' == img

    auto = mod.render_inline("Visit <https://example.com/path> or <mailto:hi@example.com> not <placeholder>")
    assert '<a href="https://example.com/path" target="_blank" rel="noopener">https://example.com/path</a>' in auto
    assert '<a href="mailto:hi@example.com">hi@example.com</a>' in auto
    assert "&lt;placeholder&gt;" in auto


def test_fenced_code_blocks_backticks_and_tildes() -> None:
    mod = _load_builder()
    md = (
        "```python\n"
        "x = '<tag>' & 1\n"
        "```\n\n"
        "~~~bash\n"
        "echo `ok`\n"
        "~~~\n"
    )
    body, _, _ = mod.render_markdown(md)
    assert '<span class="code-lang">python</span>' in body
    assert '<code class="language-python">x = \'&lt;tag&gt;\' &amp; 1</code>' in body
    assert '<span class="code-lang">bash</span>' in body
    assert '<code class="language-bash">echo `ok`</code>' in body


def test_gfm_table_alignment_and_escaped_pipes() -> None:
    mod = _load_builder()
    md = (
        "| Left | Center | Right |\n"
        "|:---|:---:|---:|\n"
        "| `a\\|b` | **mid** | 42 \\| 99 |\n"
    )
    body, _, _ = mod.render_markdown(md)
    assert '<th style="text-align:left">Left</th>' in body
    assert '<th style="text-align:center">Center</th>' in body
    assert '<th style="text-align:right">Right</th>' in body
    assert '<td style="text-align:left"><code>a|b</code></td>' in body
    assert '<td style="text-align:center"><strong>mid</strong></td>' in body
    assert '<td style="text-align:right">42 | 99</td>' in body


def test_nested_lists_and_task_lists() -> None:
    mod = _load_builder()
    md = (
        "- [x] Completed task\n"
        "- [ ] Open task\n"
        "  - Nested bullet\n"
        "  1. Ordered child\n"
        "  2. Second child\n"
    )
    body, _, _ = mod.render_markdown(md)
    assert 'class="task-list-item"' in body
    assert '<input type="checkbox" class="task-checkbox" disabled checked>' in body
    assert '<input type="checkbox" class="task-checkbox" disabled>' in body
    assert "<ul>" in body and "<ol>" in body
    assert "Nested bullet" in body and "Ordered child" in body


def test_blockquotes_and_github_alerts() -> None:
    mod = _load_builder()
    md = (
        "> Outer quote\n"
        "> > Nested quote\n\n"
        "> [!NOTE]\n"
        "> Useful **note** here.\n\n"
        "> [!WARNING]\n"
        "> Careful with `rm`.\n"
    )
    body, _, _ = mod.render_markdown(md)
    assert body.count("<blockquote>") == 2
    assert "Outer quote" in body and "Nested quote" in body
    assert 'class="md-alert md-alert-note"' in body
    assert '<div class="md-alert-title">Note</div>' in body
    assert "<strong>note</strong>" in body
    assert 'class="md-alert md-alert-warning"' in body
    assert '<div class="md-alert-title">Warning</div>' in body
    assert "<code>rm</code>" in body


def test_setext_headings_hr_and_toc() -> None:
    mod = _load_builder()
    md = (
        "Main Title\n"
        "==========\n\n"
        "Section One\n"
        "-----------\n\n"
        "---\n\n"
        "## Section One\n"
    )
    body, headings, title = mod.render_markdown(md)
    assert title == "Main Title"
    assert '<h1 id="main-title">Main Title</h1>' in body
    assert '<h2 id="section-one">Section One</h2>' in body
    assert '<h2 id="section-one-2">Section One</h2>' in body
    assert "<hr>" in body
    toc = mod.build_toc_html(headings)
    assert 'class="doc-toc"' in toc
    assert 'href="#section-one"' in toc
    assert 'href="#section-one-2"' in toc


def test_smart_relative_link_rewriting() -> None:
    mod = _load_builder()
    rendered_map = {
        (DOCS_DIR / "using.md").resolve(): (RENDERED_DIR / "using.html").resolve(),
        (DOCS_DIR / "adr" / "0001-no-in-process-llm.md").resolve(): (
            RENDERED_DIR / "adr" / "0001-no-in-process-llm.html"
        ).resolve(),
    }
    adr_rewriter = mod.make_link_rewriter(
        src_md=DOCS_DIR / "adr" / "README.md",
        rendered_html=RENDERED_DIR / "adr" / "README.html",
        rendered_map=rendered_map,
    )
    assert adr_rewriter("0001-no-in-process-llm.md") == "0001-no-in-process-llm.html"
    assert adr_rewriter("docs/using.md") == "../using.html"

    top_rewriter = mod.make_link_rewriter(
        src_md=DOCS_DIR / "data-model.md",
        rendered_html=RENDERED_DIR / "data-model.html",
        rendered_map=rendered_map,
    )
    assert top_rewriter("docs/using.md#cli") == "using.html#cli"
    assert top_rewriter("../src/casper/models.py") == "../../src/casper/models.py"
