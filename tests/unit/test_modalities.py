"""TC-014 & TC-033 (HTML escaping): Unit tests for modality formatting and counting."""

from __future__ import annotations

import html
import re

import pytest

from casper.libraries import load_libraries
from casper.modalities import count_rendered, format_draft
from casper.models import Draft, DraftSection, MarkupKind, Modality, Sentence


def _sample_draft(*, title: str | None = "Q3 Release Update") -> Draft:
    return Draft(
        title=title,
        sections=(
            DraftSection(
                name="status",
                heading="Status",
                sentences=(Sentence(text="The release is on track.", fact_ids=("f001",)),),
            ),
            DraftSection(
                name="progress",
                heading="Progress",
                sentences=(
                    Sentence(text="We shipped the new parser.", fact_ids=("f002",)),
                    Sentence(text="Response time improved by 20%.", fact_ids=("f003",)),
                ),
            ),
            DraftSection(
                name="empty_section",
                heading="Should Be Skipped",
                sentences=(),
            ),
            DraftSection(
                name="asks",
                heading="Asks",
                sentences=(
                    Sentence(text="Please approve the rollout budget.", fact_ids=("f004",)),
                    Sentence(text="Please let me know if you approve.", fact_ids=(), frame=True),
                ),
            ),
        ),
    )


def _custom_modality(
    *,
    markup: MarkupKind,
    title: bool = True,
    headings: str = "h2",
    bullets: bool = True,
) -> Modality:
    return Modality(
        id=f"custom_{markup}",
        markup=markup,
        max_words=500,
        max_chars=5000,
        title=title,
        headings=headings,
        bullets=bullets,
        description="Custom test modality",
    )


class TestShippedModalities:
    @pytest.mark.parametrize("modality_id", ["slack", "email", "memo", "article", "plain"])
    def test_wording_preserved_and_empty_sections_skipped(self, modality_id: str) -> None:
        libs = load_libraries()
        modality = libs.modalities[modality_id]
        draft = _sample_draft()

        rendered = format_draft(draft, modality)
        assert "Should Be Skipped" not in rendered

        comparable = html.unescape(rendered) if modality.markup == MarkupKind.HTML else rendered
        for section in draft.sections:
            for sent in section.sentences:
                assert sent.text in comparable

    def test_slack_format(self) -> None:
        modality = load_libraries().modalities["slack"]
        rendered = format_draft(_sample_draft(), modality)

        assert "Q3 Release Update" not in rendered
        assert "*Status*\nThe release is on track." in rendered
        assert "*Progress*\n- We shipped the new parser.\n- Response time improved by 20%." in rendered
        assert "*Asks*\nPlease approve the rollout budget." in rendered
        assert "\n\nPlease let me know if you approve." in rendered
        assert "- Please let me know if you approve." not in rendered

    def test_email_format(self) -> None:
        modality = load_libraries().modalities["email"]
        rendered = format_draft(_sample_draft(), modality)

        assert rendered.startswith("# Q3 Release Update\n\n")
        assert "**Status**\nThe release is on track." in rendered
        assert "**Progress**\n- We shipped the new parser.\n- Response time improved by 20%." in rendered
        assert "- Please let me know if you approve." not in rendered

    def test_memo_format(self) -> None:
        modality = load_libraries().modalities["memo"]
        rendered = format_draft(_sample_draft(), modality)

        assert rendered.startswith("# Q3 Release Update\n\n")
        assert "## Status\nThe release is on track." in rendered
        assert "## Progress\n- We shipped the new parser.\n- Response time improved by 20%." in rendered
        assert "## Asks\nPlease approve the rollout budget.\n\nPlease let me know if you approve." in rendered

    def test_article_html_format(self) -> None:
        modality = load_libraries().modalities["article"]
        rendered = format_draft(_sample_draft(), modality)

        assert rendered.startswith("<article>\n<h1>Q3 Release Update</h1>\n")
        assert rendered.endswith("\n</article>")
        assert "<h2>Status</h2>\n<p>The release is on track.</p>" in rendered
        assert "<h2>Progress</h2>\n<p>We shipped the new parser. Response time improved by 20%.</p>" in rendered
        assert "<ul>" not in rendered
        assert "<p>Please approve the rollout budget.</p>\n<p>Please let me know if you approve.</p>" in rendered

    def test_plain_format(self) -> None:
        modality = load_libraries().modalities["plain"]
        rendered = format_draft(_sample_draft(), modality)

        assert "Q3 Release Update" not in rendered
        assert "Status" not in rendered
        assert "Progress" not in rendered
        assert "- " not in rendered
        assert "We shipped the new parser. Response time improved by 20%." in rendered
        assert rendered.endswith("\n\nPlease let me know if you approve.")


class TestBulletAndFrameRules:
    @pytest.mark.parametrize(
        "markup",
        [MarkupKind.MARKDOWN, MarkupKind.SLACK, MarkupKind.PLAIN, MarkupKind.HTML],
    )
    def test_bullets_require_two_non_frame_sentences_and_never_bullet_frame(
        self, markup: MarkupKind
    ) -> None:
        modality = _custom_modality(markup=markup, title=False, headings="none", bullets=True)

        # 1 non-frame + 1 frame => NOT bulleted
        one_plus_frame = Draft(
            sections=(
                DraftSection(
                    name="asks",
                    heading="Asks",
                    sentences=(
                        Sentence(text="Approve the budget.", fact_ids=("f001",)),
                        Sentence(text="Let me know.", fact_ids=(), frame=True),
                    ),
                ),
            )
        )
        out_one = format_draft(one_plus_frame, modality)
        if markup == MarkupKind.HTML:
            assert "<ul>" not in out_one
            assert "<li>" not in out_one
            assert "<p>Approve the budget.</p>\n<p>Let me know.</p>" in out_one
        else:
            assert "- " not in out_one
            assert out_one == "Approve the budget.\n\nLet me know."

        # 2 non-frame + 1 frame => non-frame bulleted, frame standalone paragraph
        two_plus_frame = Draft(
            sections=(
                DraftSection(
                    name="asks",
                    heading="Asks",
                    sentences=(
                        Sentence(text="Approve the budget.", fact_ids=("f001",)),
                        Sentence(text="Confirm the launch date.", fact_ids=("f002",)),
                        Sentence(text="Let me know.", fact_ids=(), frame=True),
                    ),
                ),
            )
        )
        out_two = format_draft(two_plus_frame, modality)
        if markup == MarkupKind.HTML:
            assert (
                "<ul>\n<li>Approve the budget.</li>\n<li>Confirm the launch date.</li>\n</ul>\n"
                "<p>Let me know.</p>"
            ) in out_two
        else:
            assert out_two == (
                "- Approve the budget.\n"
                "- Confirm the launch date.\n\n"
                "Let me know."
            )

    def test_frame_only_section_with_heading(self) -> None:
        draft = Draft(
            sections=(
                DraftSection(
                    name="closing",
                    heading="Closing",
                    sentences=(
                        Sentence(text="First closing line.", frame=True),
                        Sentence(text="Second closing line.", frame=True),
                    ),
                ),
            )
        )
        md_mod = _custom_modality(markup=MarkupKind.MARKDOWN, title=False, headings="h2", bullets=True)
        assert format_draft(draft, md_mod) == "## Closing\nFirst closing line.\n\nSecond closing line."

        html_mod = _custom_modality(markup=MarkupKind.HTML, title=False, headings="h2", bullets=True)
        assert format_draft(draft, html_mod) == (
            "<article>\n<h2>Closing</h2>\n<p>First closing line.</p>\n<p>Second closing line.</p>\n</article>"
        )


class TestTitlesAndHeadingsMatrix:
    @pytest.mark.parametrize(
        ("markup", "expected_title"),
        [
            (MarkupKind.HTML, "<h1>Launch Plan</h1>"),
            (MarkupKind.MARKDOWN, "# Launch Plan"),
            (MarkupKind.SLACK, "*Launch Plan*"),
            (MarkupKind.PLAIN, "Launch Plan"),
        ],
    )
    def test_title_rendering_per_markup(self, markup: MarkupKind, expected_title: str) -> None:
        draft = Draft(
            title="Launch Plan",
            sections=(
                DraftSection(
                    name="s",
                    heading="H",
                    sentences=(Sentence(text="Ready.", fact_ids=("f001",)),),
                ),
            ),
        )
        mod_on = _custom_modality(markup=markup, title=True, headings="none", bullets=False)
        mod_off = _custom_modality(markup=markup, title=False, headings="none", bullets=False)

        assert expected_title in format_draft(draft, mod_on)
        assert "Launch Plan" not in format_draft(draft, mod_off)

        draft_no_title = Draft(title=None, sections=draft.sections)
        assert "Launch Plan" not in format_draft(draft_no_title, mod_on)
        assert "<h1>" not in format_draft(draft_no_title, mod_on)

    @pytest.mark.parametrize(
        ("markup", "headings", "expected"),
        [
            (MarkupKind.HTML, "none", None),
            (MarkupKind.HTML, "h2", "<h2>Risks &amp; Notes</h2>"),
            (MarkupKind.HTML, "bold", "<strong>Risks &amp; Notes</strong>"),
            (MarkupKind.HTML, "slack_bold", "<strong>Risks &amp; Notes</strong>"),
            (MarkupKind.MARKDOWN, "none", None),
            (MarkupKind.MARKDOWN, "h2", "## Risks & Notes"),
            (MarkupKind.MARKDOWN, "bold", "**Risks & Notes**"),
            (MarkupKind.MARKDOWN, "slack_bold", "*Risks & Notes*"),
            (MarkupKind.SLACK, "none", None),
            (MarkupKind.SLACK, "h2", "## Risks & Notes"),
            (MarkupKind.SLACK, "bold", "*Risks & Notes*"),
            (MarkupKind.SLACK, "slack_bold", "*Risks & Notes*"),
            (MarkupKind.PLAIN, "none", None),
            (MarkupKind.PLAIN, "h2", "## Risks & Notes"),
            (MarkupKind.PLAIN, "bold", "Risks & Notes"),
            (MarkupKind.PLAIN, "slack_bold", "*Risks & Notes*"),
        ],
    )
    def test_heading_modes(
        self, markup: MarkupKind, headings: str, expected: str | None
    ) -> None:
        draft = Draft(
            sections=(
                DraftSection(
                    name="risks",
                    heading="Risks & Notes",
                    sentences=(Sentence(text="No blockers.", fact_ids=("f001",)),),
                ),
            )
        )
        mod = _custom_modality(markup=markup, title=False, headings=headings, bullets=False)
        rendered = format_draft(draft, mod)
        if expected is None:
            assert "Risks" not in rendered
        else:
            assert expected in rendered


class TestHtmlEscapingAndSecurity:
    def test_xss_payload_escaped_in_title_heading_and_sentences(self) -> None:
        payload = "<script>alert(1)</script>"
        escaped = "&lt;script&gt;alert(1)&lt;/script&gt;"
        draft = Draft(
            title=f"Title {payload}",
            sections=(
                DraftSection(
                    name="sec",
                    heading=f"Head {payload}",
                    sentences=(
                        Sentence(text=f"Body {payload}", fact_ids=("f001",)),
                        Sentence(text='Second <img src=x onerror=alert(2)> & "quotes"', fact_ids=("f002",)),
                        Sentence(text=f"Frame {payload}", frame=True),
                    ),
                ),
            ),
        )
        mod = _custom_modality(markup=MarkupKind.HTML, title=True, headings="h2", bullets=True)
        rendered = format_draft(draft, mod)

        assert "<script>" not in rendered
        assert "<img" not in rendered
        assert rendered.count(escaped) == 4
        assert "&lt;img src=x onerror=alert(2)&gt; &amp; &quot;quotes&quot;" in rendered


class TestCountRendered:
    def test_html_tags_excluded_from_word_count_but_included_in_char_count(self) -> None:
        draft = Draft(
            title="Release Summary",
            sections=(
                DraftSection(
                    name="s1",
                    heading="Status",
                    sentences=(
                        Sentence(text="All checks passed.", fact_ids=("f001",)),
                        Sentence(text="Latency stayed flat.", fact_ids=("f002",)),
                    ),
                ),
            ),
        )
        html_mod = _custom_modality(markup=MarkupKind.HTML, title=True, headings="h2", bullets=True)
        text = format_draft(draft, html_mod)
        words, chars = count_rendered(draft, html_mod)

        # "Release Summary" (2) + "Status" (1) + "All checks passed." (3) + "Latency stayed flat." (3) = 9
        assert words == 9
        assert chars == len(text)
        # Ensure HTML tags inflated chars well beyond plain words
        plain_stripped = html.unescape(re.sub(r"<[^>]+>", " ", text))
        assert chars > len(plain_stripped)

    def test_html_escaped_script_counted_as_content_word(self) -> None:
        draft = Draft(
            sections=(
                DraftSection(
                    name="s",
                    heading="H",
                    sentences=(Sentence(text="Check <script>alert(1)</script> now.", fact_ids=("f001",)),),
                ),
            )
        )
        mod = _custom_modality(markup=MarkupKind.HTML, title=False, headings="none", bullets=False)
        words, chars = count_rendered(draft, mod)
        assert words == 3
        assert chars == len(format_draft(draft, mod))

    def test_markdown_and_slack_markers_excluded_from_word_count(self) -> None:
        draft = Draft(
            title="Weekly Sync",
            sections=(
                DraftSection(
                    name="p",
                    heading="Key Highlights",
                    sentences=(
                        Sentence(text="Shipped parser v2.", fact_ids=("f001",)),
                        Sentence(text="Cut latency -12% today.", fact_ids=("f002",)),
                    ),
                ),
            ),
        )
        # Words: "Weekly Sync" (2) + "Key Highlights" (2) + "Shipped parser v2." (3) + "Cut latency -12% today." (4) = 11
        libs = load_libraries()
        for mod_id in ("memo", "email"):
            mod = libs.modalities[mod_id]
            words, chars = count_rendered(draft, mod)
            assert words == 11
            assert chars == len(format_draft(draft, mod))

        # Slack omits title -> 9 words
        slack_mod = libs.modalities["slack"]
        slack_words, slack_chars = count_rendered(draft, slack_mod)
        assert slack_words == 9
        assert slack_chars == len(format_draft(draft, slack_mod))

        # Plain omits title and headings -> 7 words
        plain_mod = libs.modalities["plain"]
        plain_words, plain_chars = count_rendered(draft, plain_mod)
        assert plain_words == 7
        assert plain_chars == len(format_draft(draft, plain_mod))

    @pytest.mark.parametrize(
        "markup",
        [MarkupKind.PLAIN, MarkupKind.MARKDOWN, MarkupKind.SLACK, MarkupKind.HTML],
    )
    def test_empty_draft_counts_zero(self, markup: MarkupKind) -> None:
        draft = Draft(sections=(DraftSection(name="empty", heading="Empty", sentences=()),))
        mod = _custom_modality(markup=markup, title=True, headings="h2", bullets=True)
        assert format_draft(draft, mod) == ""
        assert count_rendered(draft, mod) == (0, 0)
