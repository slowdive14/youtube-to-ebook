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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
