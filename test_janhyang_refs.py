"""
Tests for handing psychology articles to the 잔향 newsletter (janhyang_refs.py).

The raw transcript file must look exactly like one 잔향's own
fetch_transcript.save_raw writes — same name, frontmatter and [mm:ss]
paragraphs — or its draft and verify scripts won't take it.
"""

import yaml

from export_archive import generate_issue_markdown
from janhyang_refs import file_name, paragraphs, write_refs

VIDEO = {
    "title": "Why even savvy people fall for scams, with Stacey Wood, PhD",
    "channel": "Speaking of Psychology",
    "video_id": "pod-f832a3493930",
    "url": "https://www.apa.org/news/podcasts/speaking-of-psychology/scams",
    "audio_url": "https://cdn.example/scams.mp3",
    "published": "2026-11-18T05:00:00Z",
    "description": "Stacey Wood on why older adults are targeted.",
    "group": "psych",
    "source": "podcast",
    "transcript_segments": [
        {"start": 0.0, "text": "Welcome to Speaking of Psychology."},
        {"start": 31.0, "text": "Today we talk about scams."},
        {"start": 65.0, "text": "Stacey Wood studies them."},
        {"start": 3725.0, "text": "Thanks for listening."},
    ],
}


def article(lang):
    return {
        "title": VIDEO["title"], "channel": VIDEO["channel"], "url": VIDEO["url"],
        "video_id": VIDEO["video_id"], "source": "podcast", "group": "psych",
        "published": VIDEO["published"], "category": "health",
        "article": f"# Scams ({lang})\n\n## Who gets targeted\n\nText.\n",
        "summary": "에피소드 요약입니다." if lang == "ko" else "Episode summary.",
        "section_summaries": {"Who gets targeted": "누가 표적이 되는가."},
        "section_times": {"Who gets targeted": 65},
    }


def frontmatter(text):
    return yaml.safe_load(text.split("---\n", 2)[1])


class TestNaming:
    def test_same_name_as_janhyang_raw_path(self):
        # slugify(podcast, 24) + slugify(title, 60), as in 잔향's fetch_transcript.raw_path
        assert file_name(VIDEO["channel"], VIDEO["title"], "2026-11-18") == \
            "2026-11-18_speaking-of-psychology_why-even-savvy-people-fall-for-scams-with-stacey-wood-phd.md"

    def test_accents_and_punctuation_fold_like_janhyang(self):
        assert file_name("Café Talk", "#502 — The Rebuke!", "2026-11-11") == "2026-11-11_cafe-talk_502-the-rebuke.md"


class TestParagraphs:
    def test_about_a_minute_each_with_its_start(self):
        paras = paragraphs(VIDEO["transcript_segments"])
        assert paras[0] == "[00:00] Welcome to Speaking of Psychology. Today we talk about scams."
        assert paras[1] == "[01:05] Stacey Wood studies them."
        assert paras[2] == "[1:02:05] Thanks for listening."


class TestWriteRefs:
    def test_raw_and_reference_files(self, tmp_path):
        written = write_refs([article("en")], [article("ko")], [VIDEO], folder=tmp_path, today="2026-11-19")
        name = file_name(VIDEO["channel"], VIDEO["title"], "2026-11-18")
        raw = tmp_path / "output" / "raw" / name
        ref = tmp_path / "output" / "blog_refs" / name
        assert written == [raw, ref]

        raw_text = raw.read_text(encoding="utf-8")
        meta = frontmatter(raw_text)
        assert meta["podcast"] == "Speaking of Psychology"
        assert meta["published"] == "2026-11-18"
        assert meta["transcript_source"] == "whisper"
        assert meta["auto_captions"] is True
        assert meta["words"] == 17  # timestamps not counted
        assert "## 트랜스크립트\n\n[00:00] Welcome" in raw_text

        ref_text = ref.read_text(encoding="utf-8")
        assert frontmatter(ref_text)["blog_issue"].endswith("/issues/2026-11-19")
        assert "- [01:05] **Who gets targeted**: 누가 표적이 되는가." in ref_text
        assert "## 한국어 기사" in ref_text and "## English article" in ref_text
        # the AI article never goes into the raw transcript 잔향 checks facts against
        assert "Who gets targeted" not in raw_text

    def test_never_overwrites_a_transcript_janhyang_fetched(self, tmp_path):
        name = file_name(VIDEO["channel"], VIDEO["title"], "2026-11-18")
        raw = tmp_path / "output" / "raw" / name
        raw.parent.mkdir(parents=True)
        raw.write_text("podscripts.co transcript", encoding="utf-8")
        write_refs([article("en")], [article("ko")], [VIDEO], folder=tmp_path, today="2026-11-19")
        assert raw.read_text(encoding="utf-8") == "podscripts.co transcript"
        assert (tmp_path / "output" / "blog_refs" / name).exists()

    def test_only_psychology_articles(self, tmp_path):
        other = {**article("en"), "group": "", "video_id": "abcdefghijk"}
        assert write_refs([other], [], [VIDEO], folder=tmp_path) == []

    def test_skipped_when_the_folder_is_not_there(self, tmp_path):
        assert write_refs([article("en")], [article("ko")], [VIDEO], folder=tmp_path / "missing") == []


class TestIssueAttribution:
    def test_podcast_episodes_are_listened_to(self):
        _, md = generate_issue_markdown([article("en")], [article("ko")], None, subject="s")
        assert f'> Based on **"{VIDEO["title"]}"** from **Speaking of Psychology**' in md
        assert f"> [Listen to the original episode]({VIDEO['url']})" in md
        assert f"> [원본 에피소드 듣기]({VIDEO['url']})" in md
        assert "[[AT:" not in md  # no YouTube video, no clip rows
