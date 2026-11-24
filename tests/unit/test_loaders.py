"""TC-006 & TC-024: Multi-format document loader tests and unicode/boundary tests."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfWriter

from casper.documents import prose_blocks, prose_word_count
from casper.loaders import collect_input_paths, load_bytes, load_document
from casper.models import BlockKind
from casper.rewrites import ALLOWED_RULE_TOKENS, REWRITE_RULES, TOKEN_RE, merge_pair_semicolon

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _make_docx_bytes() -> bytes:
    d = DocxDocument()
    d.core_properties.title = "Quarterly Architecture Notes"
    d.core_properties.author = "Samira Chen"
    d.add_heading("Quarterly Architecture Notes", level=1)
    d.add_heading("Key Findings", level=2)
    d.add_paragraph("We reduced cold-start latency by 35% after caching compiled schemas.")
    d.add_paragraph("First bullet item", style="List Bullet")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _make_pdf_bytes() -> bytes:
    # Minimal valid PDF with a blank page plus metadata to test pypdf roundtrip
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Brief Report", "/Author": "Samira Chen"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_odt_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr(
            "content.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            '<office:body><office:text>'
            '<text:h text:outline-level="1">ODT Title</text:h>'
            '<text:h text:outline-level="2">Details</text:h>'
            '<text:p>This ODT paragraph confirms OpenDocument loading works.</text:p>'
            '</office:text></office:body></office:document-content>',
        )
    return buf.getvalue()


def test_load_html_metadata_and_voice_exclusion() -> None:
    doc = load_document(FIXTURES / "sample.html")
    assert doc.format == "html"
    assert doc.title == "Measuring Tail Latency at Scale"
    assert "Samira Chen" in doc.authors
    assert doc.published == "2026-10-01"
    assert doc.modified == "2026-10-05"
    assert doc.canonical_url == "https://example.org/tail-latency"
    assert doc.description == "How we measure tail latency in production."
    assert len(doc.sha256) == 64

    kinds = {b.kind for b in doc.blocks}
    assert BlockKind.SUMMARY in kinds
    assert BlockKind.AUDIENCE in kinds
    assert BlockKind.RESOURCES in kinds
    assert BlockKind.PARAGRAPH in kinds
    assert BlockKind.LIST_ITEM in kinds
    assert BlockKind.QUOTE in kinds
    assert BlockKind.CODE in kinds

    prose_texts = " ".join(b.text for b in prose_blocks(doc))
    assert "excluded from voice" not in prose_texts
    assert "Averages hide outliers" in prose_texts
    assert prose_word_count(doc) > 15


def test_load_markdown_front_matter_and_key_value_preservation() -> None:
    doc = load_document(FIXTURES / "status_notes.md")
    assert doc.format == "markdown"
    assert doc.title == "Edge Cache Migration Status"
    assert doc.authors == ("Alex Rivera",)
    assert doc.published == "2026-11-15"

    para_texts = [b.text for b in doc.blocks if b.kind == BlockKind.PARAGRAPH]
    assert any(t.startswith("Status:") for t in para_texts)
    assert any(t.startswith("Owner:") for t in para_texts)
    assert any(t.startswith("Ask:") for t in para_texts)
    # Key: value lines must NOT be collapsed into one paragraph
    assert len(para_texts) >= 9


def test_load_latex_rtf_docx_pdf_odt_csv_yaml() -> None:
    tex_doc = load_document(FIXTURES / "sample.tex")
    assert tex_doc.format == "latex"
    assert tex_doc.title == "Deterministic Pipelines"
    assert tex_doc.authors == ("Samira Chen",)
    assert any(b.kind == BlockKind.HEADING and b.text == "Overview" for b in tex_doc.blocks)
    assert any(b.kind == BlockKind.LIST_ITEM for b in tex_doc.blocks)
    assert any(b.kind == BlockKind.QUOTE for b in tex_doc.blocks)

    rtf_doc = load_document(FIXTURES / "sample.rtf")
    assert rtf_doc.format == "rtf"
    assert len(rtf_doc.blocks) >= 2

    docx_doc = load_bytes(_make_docx_bytes(), "notes.docx")
    assert docx_doc.format == "docx"
    assert docx_doc.title == "Quarterly Architecture Notes"
    assert any(b.kind == BlockKind.HEADING and b.text == "Key Findings" for b in docx_doc.blocks)
    assert any(b.kind == BlockKind.LIST_ITEM for b in docx_doc.blocks)

    pdf_doc = load_bytes(_make_pdf_bytes(), "report.pdf")
    assert pdf_doc.format == "pdf"
    assert pdf_doc.title == "Brief Report"

    odt_doc = load_bytes(_make_odt_bytes(), "notes.odt")
    assert odt_doc.format == "odt"
    assert odt_doc.title == "ODT Title"
    assert any("OpenDocument" in b.text for b in odt_doc.blocks)

    csv_doc = load_document(FIXTURES / "sample.csv")
    assert csv_doc.format == "csv"
    assert any(b.text == "owner: Elena Park" for b in csv_doc.blocks)

    yaml_doc = load_document(FIXTURES / "sample.yaml")
    assert yaml_doc.format == "yaml"
    assert yaml_doc.title == "Q4 Platform Update"
    assert any("status: On track" in b.text for b in yaml_doc.blocks)


def test_tc024_unicode_contractions_and_skip_asset_folders(tmp_path: Path) -> None:
    raw = (
        "“Smart quotes” — cafés, naïve résumé, 🚀 rocket, and it doesn't break.\n\n"
        "Status: Everything doesn't fail on UTF-8.\n"
    ).encode()
    doc = load_bytes(raw, "unicode.md")
    assert "doesn't" in doc.blocks[0].text
    assert "🚀" in doc.blocks[0].text
    assert "doesn't" in TOKEN_RE.findall(doc.blocks[0].text)

    # *_files and hidden directories must be skipped by collect_input_paths
    (tmp_path / "good.md").write_text("Hello world.", encoding="utf-8")
    assets = tmp_path / "page_files"
    assets.mkdir()
    (assets / "junk.html").write_text("<p>ignore</p>", encoding="utf-8")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.md").write_text("ignore", encoding="utf-8")

    collected = collect_input_paths([tmp_path])
    assert [Path(p).name for p in collected] == ["good.md"]


def test_rewrites_registry_and_semicolon_proper_noun_preservation() -> None:
    assert len(REWRITE_RULES) == 5
    assert "doesn't" in ALLOWED_RULE_TOKENS
    assert "also" in ALLOWED_RULE_TOKENS
    merged = merge_pair_semicolon(
        "Latency dropped today.",
        "Priya verified the rollout.",
        protected_names=("Priya",),
    )
    assert merged == "Latency dropped today; Priya verified the rollout."
    merged_common = merge_pair_semicolon("Latency dropped today.", "The cache stayed warm.")
    assert merged_common == "Latency dropped today; the cache stayed warm."
