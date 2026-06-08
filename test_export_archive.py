"""
Tests for export_archive.py
Tests markdown generation logic. R2 upload and git push are mocked.
"""

import pytest
from unittest.mock import patch, MagicMock
from export_archive import (
    generate_issue_markdown,
    _escape_yaml,
    _inject_summary_after_h1,
    embed_frames,
)


# --- Sample data ---

SAMPLE_EN_ARTICLES = [
    {
        "title": "The Future of AI",
        "channel": "TechChannel",
        "url": "https://youtube.com/watch?v=abc123",
        "article": "# AI Revolution\n\nArtificial Intelligence is transforming...",
    },
    {
        "title": 'Testing "Quotes" in Title',
        "channel": "DevChannel",
        "url": "https://youtube.com/watch?v=def456",
        "article": "# Test Article\n\nSome content here...",
    },
]

SAMPLE_KO_ARTICLES = [
    {
        "title": "AI의 미래",
        "channel": "TechChannel",
        "url": "https://youtube.com/watch?v=abc123",
        "article": "# AI 혁명\n\n인공지능이 세상을 바꾸고 있습니다...",
    },
]


# --- Tests ---

class TestEscapeYaml:
    def test_escapes_double_quotes(self):
        assert _escape_yaml('He said "hello"') == 'He said \\"hello\\"'

    def test_no_change_without_quotes(self):
        assert _escape_yaml("No quotes here") == "No quotes here"


class TestGenerateIssueMarkdown:
    def test_generates_frontmatter_with_date(self):
        filename, content = generate_issue_markdown(
            SAMPLE_EN_ARTICLES, [], [], subject="Test Subject"
        )
        assert filename.endswith(".md")
        assert "---" in content
        assert 'subject: "Test Subject"' in content
        assert "date:" in content

    def test_contains_english_articles(self):
        _, content = generate_issue_markdown(SAMPLE_EN_ARTICLES, [], [])
        assert "## English" in content
        assert "AI Revolution" in content
        assert "TechChannel" in content
        assert "https://youtube.com/watch?v=abc123" in content

    def test_contains_korean_articles(self):
        _, content = generate_issue_markdown([], SAMPLE_KO_ARTICLES, [])
        assert "## 한국어" in content
        assert "AI 혁명" in content

    def test_both_languages_with_divider(self):
        _, content = generate_issue_markdown(
            SAMPLE_EN_ARTICLES, SAMPLE_KO_ARTICLES, []
        )
        assert "## English" in content
        assert "## 한국어" in content

    def test_audio_urls_in_frontmatter(self):
        urls = ["https://r2.example.com/audio/2026/03/04/test.mp3"]
        _, content = generate_issue_markdown(SAMPLE_EN_ARTICLES, [], urls)
        assert "audioUrls:" in content
        assert "https://r2.example.com/audio/2026/03/04/test.mp3" in content

    def test_articles_metadata_in_frontmatter(self):
        _, content = generate_issue_markdown(SAMPLE_EN_ARTICLES, [], [])
        assert "articles:" in content
        assert 'title: "The Future of AI"' in content
        assert 'channel: "TechChannel"' in content

    def test_escapes_quotes_in_titles(self):
        _, content = generate_issue_markdown(SAMPLE_EN_ARTICLES, [], [])
        assert 'title: "Testing \\"Quotes\\" in Title"' in content

    def test_auto_subject_from_first_article(self):
        _, content = generate_issue_markdown(SAMPLE_EN_ARTICLES, [], [])
        assert 'subject: "The Future of AI & 1 more"' in content

    def test_single_article_subject(self):
        single = [SAMPLE_EN_ARTICLES[0]]
        _, content = generate_issue_markdown(single, [], [])
        assert 'subject: "The Future of AI"' in content

    def test_empty_articles(self):
        _, content = generate_issue_markdown([], [], [])
        assert "---" in content
        assert "YouTube Digest" in content

    def test_summary_renders_as_h3_after_article_h1(self):
        """Summary must be an H3 inside the article body so the site's TOC
        (which queries h1, h2, h3) picks it up. Placing it AFTER the first H1
        also makes it a child of the article group in the mobile TOC."""
        articles = [{
            "title": "Sleep and the Brain",
            "channel": "NeuroChannel",
            "url": "https://youtube.com/watch?v=xyz",
            "article": "# Headline\n\nFull body...",
            "summary": "Walker presents fMRI evidence that one night of sleep "
                       "deprivation reduces hippocampal learning capacity by 40%.",
        }]
        _, content = generate_issue_markdown(articles, [], [])
        # Frontmatter still carries the summary for the listing page
        assert "summary: >-" in content
        # Body must use H3 heading (not bold paragraph) so TOC picks it up
        assert "### Episode summary" in content
        assert "**Episode summary**" not in content  # old layout gone
        assert "Walker presents fMRI evidence" in content
        # H3 must appear AFTER the article's H1, not before it
        h1_pos = content.find("# Headline")
        h3_pos = content.find("### Episode summary")
        assert h1_pos != -1 and h3_pos != -1
        assert h3_pos > h1_pos, "Summary H3 must come after the article H1"

    def test_korean_summary_uses_korean_label(self):
        ko_articles = [{
            "title": "수면과 뇌",
            "channel": "NeuroCh",
            "url": "https://youtube.com/watch?v=ko1",
            "article": "# 헤드라인\n\n본문...",
            "summary": "워커는 하룻밤 수면 부족이 해마 학습 능력을 40% 떨어뜨린다고 주장한다.",
        }]
        _, content = generate_issue_markdown([], ko_articles, [])
        assert "### 에피소드 요약" in content
        assert "**에피소드 요약**" not in content
        h1_pos = content.find("# 헤드라인")
        h3_pos = content.find("### 에피소드 요약")
        assert h3_pos > h1_pos

    def test_multi_paragraph_summary_preserves_blank_lines(self):
        # Folded YAML scalar needs blank lines preserved so paragraph breaks
        # survive in the rendered archive site.
        multi_para = (
            "First paragraph introducing the topic and main claim.\n\n"
            "Second paragraph with specific evidence: 40% reduction.\n\n"
            "Third paragraph with takeaway."
        )
        articles = [{
            "title": "Multi-Para Episode",
            "channel": "Ch",
            "url": "https://youtube.com/watch?v=mp",
            "article": "# Body\n\nText.",
            "summary": multi_para,
        }]
        _, content = generate_issue_markdown(articles, [], [])
        # Each paragraph's leading content should be present
        assert "First paragraph introducing" in content
        assert "Second paragraph with specific evidence" in content
        assert "Third paragraph with takeaway" in content
        # Frontmatter should use folded scalar
        assert "summary: >-" in content

    def test_summary_missing_is_optional(self):
        # Articles without a summary field must still render cleanly
        articles = [{
            "title": "No Summary Here",
            "channel": "Ch",
            "url": "https://youtube.com/watch?v=000",
            "article": "# Body\n\nText.",
        }]
        _, content = generate_issue_markdown(articles, [], [])
        assert "summary: >-" not in content
        assert "### Episode summary" not in content
        assert "**Episode summary**" not in content


class TestInjectSummaryAfterH1:
    """Unit tests for _inject_summary_after_h1 — placing the summary as an
    H3 immediately after the article's first H1."""

    def test_h1_found_summary_injected_after(self):
        article = "# Article Title\n\nBody paragraph.\n\n## Section\n\nMore."
        result = _inject_summary_after_h1(article, "Short summary.", label="Episode summary")
        # H1 stays first, then H3 + summary, then original body
        lines = result.split("\n")
        # Find indices
        h1_idx = next(i for i, l in enumerate(lines) if l.startswith("# "))
        h3_idx = next(i for i, l in enumerate(lines) if l.startswith("### Episode summary"))
        assert h3_idx > h1_idx
        # H3 must come BEFORE the existing ## section
        h2_idx = next(i for i, l in enumerate(lines) if l.startswith("## Section"))
        assert h3_idx < h2_idx
        # Summary body present
        assert "Short summary." in result

    def test_korean_label_renders(self):
        result = _inject_summary_after_h1(
            "# 제목\n\n본문.",
            "한 줄 요약.",
            label="에피소드 요약",
        )
        assert "### 에피소드 요약" in result
        assert "한 줄 요약." in result

    def test_no_h1_fallback_prepends(self):
        # If somehow no H1 exists, summary must still appear (not lost)
        article = "Body without any heading.\n\nMore body."
        result = _inject_summary_after_h1(article, "Summary.", label="Episode summary")
        assert "### Episode summary" in result
        assert "Summary." in result
        # Summary should appear at the start since no H1 to anchor to
        assert result.index("### Episode summary") < result.index("Body without")

    def test_only_first_h1_used_when_multiple(self):
        article = "# First H1\n\nBody.\n\n# Second H1\n\nMore."
        result = _inject_summary_after_h1(article, "Summary.", label="Episode summary")
        # Summary appears once, right after first H1
        assert result.count("### Episode summary") == 1
        first_h1_pos = result.find("# First H1")
        second_h1_pos = result.find("# Second H1")
        h3_pos = result.find("### Episode summary")
        assert first_h1_pos < h3_pos < second_h1_pos

    def test_empty_summary_returns_article_unchanged(self):
        article = "# Title\n\nBody."
        assert _inject_summary_after_h1(article, "", label="Episode summary") == article
        assert _inject_summary_after_h1(article, "   ", label="Episode summary") == article

    def test_multi_paragraph_summary_preserved(self):
        summary = "First paragraph.\n\nSecond paragraph."
        result = _inject_summary_after_h1(
            "# Title\n\nBody.", summary, label="Episode summary"
        )
        assert "First paragraph." in result
        assert "Second paragraph." in result
        # Blank line between paragraphs preserved
        assert "First paragraph.\n\nSecond paragraph." in result


class TestEmbedFrames:
    """Swap [[FRAME:<seconds>]] markers for markdown images."""

    def test_replaces_marker_with_image(self):
        md = "Intro paragraph.\n\n[[FRAME:90]]\n\nMore text."
        frame_map = {90: ("https://r2.dev/img/a.jpg", "A sleep cycle diagram")}
        out = embed_frames(md, frame_map)
        assert "![A sleep cycle diagram](https://r2.dev/img/a.jpg)" in out
        assert "[[FRAME:90]]" not in out
        # visible caption present
        assert "A sleep cycle diagram" in out

    def test_multiple_markers(self):
        md = "[[FRAME:10]]\n\nmiddle\n\n[[FRAME:60]]"
        frame_map = {
            10: ("https://r2.dev/1.jpg", "first"),
            60: ("https://r2.dev/2.jpg", "second"),
        }
        out = embed_frames(md, frame_map)
        assert "![first](https://r2.dev/1.jpg)" in out
        assert "![second](https://r2.dev/2.jpg)" in out
        assert out.find("first") < out.find("second")

    def test_orphan_marker_stripped(self):
        # a marker whose frame failed to capture must not leak as literal text
        md = "Body.\n\n[[FRAME:999]]\n\nEnd."
        out = embed_frames(md, {})
        assert "[[FRAME:999]]" not in out
        assert "Body." in out and "End." in out

    def test_marker_without_map_entry_stripped(self):
        md = "[[FRAME:10]]\n\n[[FRAME:20]]"
        frame_map = {10: ("https://r2.dev/1.jpg", "only one")}
        out = embed_frames(md, frame_map)
        assert "![only one](https://r2.dev/1.jpg)" in out
        assert "[[FRAME:20]]" not in out  # orphan removed

    def test_frame_without_marker_appended_as_gallery(self):
        md = "Body with no markers at all."
        frame_map = {42: ("https://r2.dev/x.jpg", "orphan frame")}
        out = embed_frames(md, frame_map)
        assert "![orphan frame](https://r2.dev/x.jpg)" in out
        assert out.find("Body with no markers") < out.find("orphan frame")

    def test_no_markers_no_frames_unchanged(self):
        md = "Just text.\n\nMore."
        assert embed_frames(md, {}) == md

    def test_collapses_blank_lines_after_strip(self):
        md = "A.\n\n[[FRAME:5]]\n\nB."
        out = embed_frames(md, {})
        # no triple-newline gaps left behind
        assert "\n\n\n" not in out

    def test_caption_with_parens_does_not_break_link(self):
        md = "[[FRAME:7]]"
        frame_map = {7: ("https://r2.dev/y.jpg", "chart (2026 data)")}
        out = embed_frames(md, frame_map)
        # the URL must remain intact and clickable
        assert "(https://r2.dev/y.jpg)" in out


class TestPerArticleFrames:
    """Article carrying frame_moments + frame_map: inject at anchor, then embed,
    while keeping the canonical article text marker-free for audio/email."""

    def test_anchor_inline_image_in_body(self):
        article = {
            "title": "Sleep",
            "channel": "Ch",
            "url": "https://youtube.com/watch?v=z",
            "article": "# Headline\n\nDeep sleep restores memory consolidation overnight.\n\nNext para.",
            "summary": "s",
            "frame_moments": [
                {"seconds": 90, "timestamp": "01:30",
                 "caption": "Brain scan", "anchor": "restores memory consolidation"}
            ],
            "frame_map": {90: ("https://r2.dev/z_01-30.jpg", "Brain scan")},
        }
        _, content = generate_issue_markdown([article], [], [])
        assert "![Brain scan](https://r2.dev/z_01-30.jpg)" in content
        assert "[[FRAME:90]]" not in content
        # image must land near the anchor paragraph (before "Next para")
        assert content.find("Brain scan") < content.find("Next para")

    def test_canonical_article_text_stays_marker_free(self):
        # The dict's own 'article' field must not be mutated with markers
        article = {
            "title": "T", "channel": "C", "url": "u",
            "article": "# H\n\nthe key insight here matters.\n",
            "frame_moments": [{"seconds": 5, "timestamp": "00:05",
                               "caption": "c", "anchor": "the key insight here"}],
            "frame_map": {5: ("https://r2.dev/a.jpg", "c")},
        }
        generate_issue_markdown([article], [], [])
        assert "[[FRAME:" not in article["article"]
        assert "![c]" not in article["article"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
