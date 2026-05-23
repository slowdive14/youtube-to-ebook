"""
Tests for export_archive.py
Tests markdown generation logic. R2 upload and git push are mocked.
"""

import pytest
from unittest.mock import patch, MagicMock
from export_archive import generate_issue_markdown, _escape_yaml


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

    def test_summary_in_frontmatter_and_body(self):
        articles = [{
            "title": "Sleep and the Brain",
            "channel": "NeuroChannel",
            "url": "https://youtube.com/watch?v=xyz",
            "article": "# Headline\n\nFull body...",
            "summary": "Walker presents fMRI evidence that one night of sleep "
                       "deprivation reduces hippocampal learning capacity by 40%.",
        }]
        _, content = generate_issue_markdown(articles, [], [])
        # Frontmatter carries the summary so the listing page can render it
        assert "summary: >-" in content
        # Body has a clearly labeled summary block above the article
        assert "**Episode summary**" in content
        assert "Walker presents fMRI evidence" in content

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
        assert "**Episode summary**" not in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
