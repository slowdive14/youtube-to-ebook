"""
Tests for article categories on the archive site.

The category is the subject area Step 1c/1d gives each video
(select_videos.DOMAINS). The pipeline writes it into the issue's frontmatter;
scripts/backfill_categories.py adds it to issues made before that, editing
only `category:` lines so nothing else in a hand-touched file can change.
"""

import yaml

from export_archive import generate_issue_markdown
from scripts.backfill_categories import set_categories


FRONTMATTER = """---
title: "YouTube Digest — 2026-10-02"
date: 2026-10-02
subject: "Two episodes"
articles:
  - title: "First episode"
    channel: "NPR Podcasts"
    url: "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    summary: >-
      A summary that mentions url: and category: in its text
      - and a line starting with a dash.
  - title: "Second episode"
    channel: "Vox"
    url: "https://www.youtube.com/watch?v=bbbbbbbbbbb"
speakingPrompt:
  topic: "x"
  question_ko: "질문"
  frame: "I ___"
  model: "I do."
  expressions:
    - en: "title: not an article"
      ko: ""
---
"""


def parsed(fm):
    return yaml.safe_load(fm.strip().strip("-"))


class TestSetCategories:
    def test_adds_a_category_to_each_listed_article(self):
        out = set_categories(FRONTMATTER, {0: "culture", 1: "politics"})
        arts = parsed(out)["articles"]
        assert [a["category"] for a in arts] == ["culture", "politics"]

    def test_changes_nothing_but_the_added_lines(self):
        out = set_categories(FRONTMATTER, {0: "culture", 1: "politics"})
        added = [l for l in out.split("\n") if l not in FRONTMATTER.split("\n")]
        assert added == ['    category: "culture"', '    category: "politics"']
        assert out.replace('    category: "culture"\n', "").replace('    category: "politics"\n', "") == FRONTMATTER

    def test_only_the_given_articles_are_touched(self):
        arts = parsed(set_categories(FRONTMATTER, {1: "politics"}))["articles"]
        assert "category" not in arts[0]
        assert arts[1]["category"] == "politics"

    def test_summary_and_speaking_prompt_survive(self):
        data = parsed(set_categories(FRONTMATTER, {0: "culture", 1: "politics"}))
        assert data["articles"][0]["summary"].startswith("A summary that mentions url:")
        assert data["speakingPrompt"]["expressions"][0]["en"] == "title: not an article"

    def test_replaces_an_existing_category_instead_of_duplicating_it(self):
        once = set_categories(FRONTMATTER, {0: "culture"})
        twice = set_categories(once, {0: "health"})
        assert twice.count('\n    category: "') == 1
        assert parsed(twice)["articles"][0]["category"] == "health"

    def test_nothing_to_set_returns_the_input(self):
        assert set_categories(FRONTMATTER, {}) == FRONTMATTER


class TestExportWritesCategory:
    def article(self, title, category=""):
        return {
            "title": title,
            "channel": "Vox",
            "url": "https://www.youtube.com/watch?v=ccccccccccc",
            "category": category,
            "article": f"# {title}\n\nBody.\n",
            "summary": "",
        }

    def test_category_lands_in_the_frontmatter(self):
        _, content = generate_issue_markdown(
            [self.article("A", "science"), self.article("B")], [], None, subject="s"
        )
        fm = content.split("---\n", 2)[1]
        arts = yaml.safe_load(fm)["articles"]
        assert arts[0]["category"] == "science"
        assert "category" not in arts[1]  # unlabelled stays absent, not ""
