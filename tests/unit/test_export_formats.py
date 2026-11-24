"""Unit tests for multi-format markup loaders and multi-format document exporters."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from pypdf import PdfReader

from casper.errors import InputError
from casper.loaders import SUPPORTED_UPLOAD_EXTENSIONS, load_bytes
from casper.loaders.markup import parse_asciidoc, parse_org, parse_rst
from casper.modalities import EXPORT_FORMATS, export_document
from casper.models import BlockKind

SAMPLE_MD = """# Edge Cache Rollout

## Status
The edge cache rollout reached 80% of production traffic on schedule.

## Highlights
- Cold-start latency dropped by 35% across primary regions.
- Error budget stayed green with zero customer escalations.

## Next Steps
Complete the final regional cutover before Friday.
"""

KEY_PHRASES = (
    "Edge Cache Rollout",
    "80% of production traffic",
    "Cold-start latency dropped by 35%",
    "zero customer escalations",
    "final regional cutover",
)

ROUNDTRIP_FORMATS = (
    "txt",
    "md",
    "adoc",
    "html",
    "pdf",
    "docx",
    "odt",
    "rtf",
    "tex",
    "rst",
    "org",
)


class TestExportFormats:
    def test_all_twelve_formats_registered(self) -> None:
        expected = {
            "txt",
            "md",
            "adoc",
            "html",
            "pdf",
            "docx",
            "odt",
            "rtf",
            "tex",
            "rst",
            "org",
            "json",
        }
        assert set(EXPORT_FORMATS) == expected

    @pytest.mark.parametrize("fmt", ROUNDTRIP_FORMATS)
    def test_export_and_roundtrip_load_bytes(self, fmt: str) -> None:
        payload, mime_type, filename = export_document(
            SAMPLE_MD,
            fmt,
            title="Edge Cache Rollout",
        )
        _label, ext, expected_mime = EXPORT_FORMATS[fmt]
        assert isinstance(payload, bytes) and len(payload) > 0
        assert mime_type == expected_mime
        assert filename == f"edge-cache-rollout.{ext}"

        # Deterministic byte-identical output across repeated calls
        payload_again, _, _ = export_document(SAMPLE_MD, fmt, title="Edge Cache Rollout")
        assert payload == payload_again

        # Round-trip through casper.loaders.load_bytes
        doc = load_bytes(payload, filename)
        combined_parts = [doc.title or "", *(b.text for b in doc.blocks)]
        combined = " ".join(combined_parts)
        for phrase in KEY_PHRASES:
            # LaTeX escapes '%' as '\%' and loaders/latex.py preserves escaped symbols
            normalized = combined.replace(r"\%", "%")
            assert phrase in normalized, f"Missing {phrase!r} in {fmt} round-trip: {combined!r}"

    def test_export_json_bundle(self) -> None:
        payload, mime_type, filename = export_document(
            SAMPLE_MD,
            "json",
            title="Edge Cache Rollout",
            metadata={"structure": "status_update", "modality": "memo", "seed": 42},
        )
        assert mime_type == "application/json; charset=utf-8"
        assert filename == "edge-cache-rollout.json"

        parsed = json.loads(payload.decode("utf-8"))
        assert parsed["title"] == "Edge Cache Rollout"
        assert parsed["text"] == SAMPLE_MD
        assert parsed["structure"] == "status_update"
        assert parsed["modality"] == "memo"
        assert parsed["seed"] == 42

    def test_export_pdf_multipage_and_pypdf_readable(self) -> None:
        long_paragraphs = "\n\n".join(
            f"Paragraph {i}: Production telemetry confirms stable throughput and bounded latency."
            for i in range(1, 60)
        )
        text = f"# Long Report\n\n## Telemetry\n{long_paragraphs}\n"
        payload, mime_type, filename = export_document(text, "pdf")
        assert mime_type == "application/pdf"
        assert filename == "long-report.pdf"
        assert payload.startswith(b"%PDF-1.4")

        reader = PdfReader(io.BytesIO(payload))
        assert len(reader.pages) >= 2
        assert reader.metadata is not None
        assert reader.metadata.title == "Long Report"
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert "Paragraph 1:" in full_text
        assert "Paragraph 59:" in full_text

    def test_export_odt_uncompressed_mimetype_first(self) -> None:
        payload, _, _ = export_document(SAMPLE_MD, "odt")
        with zipfile.ZipFile(io.BytesIO(payload), "r") as zf:
            infos = zf.infolist()
            assert infos[0].filename == "mimetype"
            assert infos[0].compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype") == b"application/vnd.oasis.opendocument.text"
            names = set(zf.namelist())
            assert {"META-INF/manifest.xml", "styles.xml", "content.xml"} <= names

    def test_export_html_and_slack_inputs_and_default_slug(self) -> None:
        html_in = (
            "<article>\n<h1>Ops Digest</h1>\n<h2>Risks</h2>\n"
            "<ul>\n<li>Disk queue spike on node-4.</li>\n<li>Pending failover drill.</li>\n</ul>\n"
            "<p>No immediate customer impact.</p>\n</article>"
        )
        payload, _, filename = export_document(html_in, "md")
        decoded = payload.decode("utf-8")
        assert filename == "ops-digest.md"
        assert "# Ops Digest" in decoded
        assert "## Risks" in decoded
        assert "- Disk queue spike on node-4." in decoded

        slack_in = "*Status*\n- Latency fell 12%.\n- Error rate stayed flat."
        payload_s, _, filename_s = export_document(slack_in, "adoc")
        decoded_s = payload_s.decode("utf-8")
        assert filename_s == "casper-draft.adoc"
        assert "== Status" in decoded_s
        assert "* Latency fell 12%." in decoded_s

    def test_export_latex_escapes_special_chars(self) -> None:
        special = "# Cost & Margin_2026\n\nSaved $100k (~15% reduction) in #ops {prod}.\n"
        payload, _, _ = export_document(special, "tex")
        tex = payload.decode("utf-8")
        assert r"\documentclass{article}" in tex
        assert r"\usepackage[utf8]{inputenc}" in tex
        assert r"\&" in tex
        assert r"\_" in tex
        assert r"\$" in tex
        assert r"\%" in tex
        assert r"\#" in tex
        assert r"\{" in tex and r"\}" in tex
        assert r"\textasciitilde{}" in tex

    def test_export_rtf_unicode(self) -> None:
        payload, _, _ = export_document("# Café Résumé\n\nLatency improved — 20%.\n", "rtf")
        raw = payload.decode("ascii")
        assert raw.startswith(r"{\rtf1\ansi")
        assert r"\u" in raw
        doc = load_bytes(payload, "out.rtf")
        joined = " ".join(b.text for b in doc.blocks)
        assert "Caf" in joined
        assert "20%" in joined

    def test_invalid_export_format_raises_input_error(self) -> None:
        with pytest.raises(InputError, match="Unsupported export format"):
            export_document("Hello world", "epub")


class TestMarkupLoaders:
    def test_supported_upload_extensions_exported(self) -> None:
        for ext in (".adoc", ".asciidoc", ".rst", ".org", ".pdf", ".docx", ".odt", ".rtf", ".tex"):
            assert ext in SUPPORTED_UPLOAD_EXTENSIONS

    def test_parse_asciidoc_headings_lists_attrs_comments_and_kv(self) -> None:
        raw = (
            b"= Platform Architecture\n"
            b":author: Samira Chen\n"
            b":revdate: 2026-11-20\n"
            b":toc:\n"
            b"// Single-line comment to ignore\n"
            b"\n"
            b"== Current Status\n"
            b"Status: Green across all clusters.\n"
            b"Owner: Priya Nair\n"
            b"Risks: DNS TTL propagation lag.\n"
            b"\n"
            b"=== Action Items\n"
            b"* Rotate TLS certificates\n"
            b"- Verify staging smoke tests\n"
            b". Publish post-release notes\n"
        )
        doc = parse_asciidoc(raw, "arch.adoc")
        assert doc.format == "asciidoc"
        assert doc.title == "Platform Architecture"
        assert doc.authors == ("Samira Chen",)
        assert doc.published == "2026-11-20"
        assert any(b.kind == BlockKind.TITLE and b.text == "Platform Architecture" for b in doc.blocks)
        assert any(b.kind == BlockKind.HEADING and b.level == 2 and b.text == "Current Status" for b in doc.blocks)
        assert any(b.kind == BlockKind.HEADING and b.level == 3 and b.text == "Action Items" for b in doc.blocks)
        list_texts = [b.text for b in doc.blocks if b.kind == BlockKind.LIST_ITEM]
        assert list_texts == [
            "Rotate TLS certificates",
            "Verify staging smoke tests",
            "Publish post-release notes",
        ]
        para_texts = [b.text for b in doc.blocks if b.kind == BlockKind.PARAGRAPH]
        assert "Status: Green across all clusters." in para_texts
        assert "Owner: Priya Nair" in para_texts
        assert "Risks: DNS TTL propagation lag." in para_texts
        assert all("comment to ignore" not in b.text for b in doc.blocks)
        assert all(":toc:" not in b.text for b in doc.blocks)

        # Extension dispatch via load_bytes
        via_dispatch = load_bytes(raw, "notes.asciidoc")
        assert via_dispatch.format == "asciidoc"
        assert via_dispatch.title == "Platform Architecture"

    def test_parse_rst_headings_lists_directives_and_kv(self) -> None:
        raw = (
            b"Service Migration Plan\n"
            b"======================\n"
            b"\n"
            b".. note::\n"
            b"   Internal directive body that must be skipped.\n"
            b"\n"
            b"Status Summary\n"
            b"--------------\n"
            b"\n"
            b"Status: On track for Q4 cutover.\n"
            b"Owner: Elena Park\n"
            b"\n"
            b"Checklist\n"
            b"~~~~~~~~~\n"
            b"\n"
            b"- Migrate read replicas\n"
            b"* Validate failover alarms\n"
        )
        doc = parse_rst(raw, "plan.rst")
        assert doc.format == "rst"
        assert doc.title == "Service Migration Plan"
        assert any(b.kind == BlockKind.TITLE and b.text == "Service Migration Plan" for b in doc.blocks)
        assert any(b.kind == BlockKind.HEADING and b.level == 2 and b.text == "Status Summary" for b in doc.blocks)
        assert any(b.kind == BlockKind.HEADING and b.level == 3 and b.text == "Checklist" for b in doc.blocks)
        list_texts = [b.text for b in doc.blocks if b.kind == BlockKind.LIST_ITEM]
        assert list_texts == ["Migrate read replicas", "Validate failover alarms"]
        para_texts = [b.text for b in doc.blocks if b.kind == BlockKind.PARAGRAPH]
        assert "Status: On track for Q4 cutover." in para_texts
        assert "Owner: Elena Park" in para_texts
        assert all("must be skipped" not in b.text for b in doc.blocks)

        via_dispatch = load_bytes(raw, "plan.rst")
        assert via_dispatch.format == "rst"
        assert via_dispatch.title == "Service Migration Plan"

    def test_parse_org_title_headings_lists_comments_and_kv(self) -> None:
        raw = (
            b"#+TITLE: Quarterly Reliability Review\n"
            b"#+AUTHOR: Jordan Lee\n"
            b"#+OPTIONS: toc:nil\n"
            b"# Comment line to ignore\n"
            b"\n"
            b"* Executive Overview\n"
            b"Status: Green\n"
            b"Next Steps: Complete chaos testing.\n"
            b"\n"
            b"** Action List\n"
            b"- Audit alert thresholds\n"
            b"+ Update on-call runbooks\n"
        )
        doc = parse_org(raw, "review.org")
        assert doc.format == "org"
        assert doc.title == "Quarterly Reliability Review"
        assert doc.authors == ("Jordan Lee",)
        assert any(b.kind == BlockKind.TITLE and b.text == "Quarterly Reliability Review" for b in doc.blocks)
        assert any(b.kind == BlockKind.HEADING and b.level == 1 and b.text == "Executive Overview" for b in doc.blocks)
        assert any(b.kind == BlockKind.HEADING and b.level == 2 and b.text == "Action List" for b in doc.blocks)
        list_texts = [b.text for b in doc.blocks if b.kind == BlockKind.LIST_ITEM]
        assert list_texts == ["Audit alert thresholds", "Update on-call runbooks"]
        para_texts = [b.text for b in doc.blocks if b.kind == BlockKind.PARAGRAPH]
        assert "Status: Green" in para_texts
        assert "Next Steps: Complete chaos testing." in para_texts
        assert all("Comment line" not in b.text for b in doc.blocks)
        assert all("toc:nil" not in b.text for b in doc.blocks)

        via_dispatch = load_bytes(raw, "review.org")
        assert via_dispatch.format == "org"
        assert via_dispatch.title == "Quarterly Reliability Review"
