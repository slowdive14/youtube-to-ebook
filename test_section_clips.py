"""
Tests for per-section video clips: locating where each article section starts
in the original video, and writing that as an [[AT:<id>:<seconds>]] marker.

Pure-function tests plus the Gemini path with a mocked client. The timing
rides on the existing section-summary request, so the guard that matters most
is that it adds no request and degrades to "no clip" rather than a bad one.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

from write_articles import (
    compact_transcript,
    parse_section_times,
    inject_section_summaries,
    generate_section_guide,
    generate_section_summaries,
    CLIP_MARKER_RE,
)
from export_archive import youtube_video_id


ARTICLE = """# The Title

Intro paragraph.

## Breathing Basics

Body one.

## The 13-Minute Practice

Body two.
"""


def seg(start, text):
    return {"start": start, "text": text}


def fake_response(payload):
    return SimpleNamespace(text=payload, usage_metadata=None, candidates=[])


# ---------- compact_transcript ----------

class TestCompactTranscript:
    def test_groups_segments_into_stamped_blocks(self):
        out = compact_transcript([seg(0, "hello"), seg(10, "there"), seg(31, "next"), seg(65, "later")])
        assert out.split("\n") == ["[00:00] hello there", "[00:31] next", "[01:05] later"]

    def test_caps_words_per_block(self):
        out = compact_transcript([seg(0, " ".join(f"w{i}" for i in range(100)))])
        assert len(out.split("] ", 1)[1].split()) == 40

    def test_long_videos_get_wider_blocks_so_the_prompt_stays_bounded(self):
        three_hours = [seg(s, "word") for s in range(0, 3 * 3600, 5)]
        assert len(compact_transcript(three_hours).split("\n")) <= 151

    def test_hours_are_formatted(self):
        assert compact_transcript([seg(3725, "x")]) == "[1:02:05] x"

    def test_skips_blank_segments_and_handles_empty(self):
        assert compact_transcript([seg(0, "  "), seg(5, "kept")]) == "[00:05] kept"
        assert compact_transcript([]) == ""
        assert compact_transcript(None) == ""


# ---------- parse_section_times ----------

HEADINGS = ["Breathing Basics", "The 13-Minute Practice"]


def times_json(*rows):
    return json.dumps({"summaries": [
        {"heading": h, "summary": "s", "start": t} for h, t in rows
    ]})


class TestParseSectionTimes:
    def test_reads_mm_ss_and_h_mm_ss(self):
        out = parse_section_times(
            times_json(("Breathing Basics", "02:30"), ("The 13-Minute Practice", "1:01:00")),
            HEADINGS, last_start=4000,
        )
        assert out == {"Breathing Basics": 150, "The 13-Minute Practice": 3660}

    def test_drops_times_past_the_end_of_the_video(self):
        # A clip that opens on a blank player is worse than no clip.
        out = parse_section_times(times_json(("Breathing Basics", "45:00")), HEADINGS, last_start=600)
        assert out == {}

    def test_allows_one_block_of_slack_at_the_end(self):
        out = parse_section_times(times_json(("Breathing Basics", "10:20")), HEADINGS, last_start=600)
        assert out == {"Breathing Basics": 620}

    def test_empty_or_garbage_start_means_no_clip(self):
        out = parse_section_times(
            times_json(("Breathing Basics", ""), ("The 13-Minute Practice", "soon")),
            HEADINGS, last_start=600,
        )
        assert out == {}

    def test_matches_reformatted_headings(self):
        out = parse_section_times(times_json(("breathing basics:", "00:40")), HEADINGS, last_start=600)
        assert out == {"Breathing Basics": 40}

    def test_returns_empty_on_junk(self):
        assert parse_section_times("not json", HEADINGS, 600) == {}
        assert parse_section_times("", HEADINGS, 600) == {}


# ---------- inject_section_summaries ----------

class TestInjectWithClips:
    SUMS = {"Breathing Basics": "Breathe slowly.", "The 13-Minute Practice": "Do it daily."}

    def test_writes_the_clip_marker_right_after_the_summary(self):
        out = inject_section_summaries(
            ARTICLE, self.SUMS, times={"The 13-Minute Practice": 1100}, video_id="A3_fG1h2a_g"
        )
        lines = [l for l in out.split("\n") if l.strip()]
        i = lines.index("## The 13-Minute Practice")
        assert lines[i + 1] == "[[SUM]] Do it daily."
        assert lines[i + 2] == "[[AT:A3_fG1h2a_g:1100]]"
        assert CLIP_MARKER_RE.match(lines[i + 2])

    def test_no_clip_for_a_section_without_a_time(self):
        out = inject_section_summaries(ARTICLE, self.SUMS, times={"The 13-Minute Practice": 1100},
                                       video_id="A3_fG1h2a_g")
        assert out.count("[[AT:") == 1

    def test_no_clip_without_a_video_id(self):
        out = inject_section_summaries(ARTICLE, self.SUMS, times={"Breathing Basics": 10}, video_id=None)
        assert "[[AT:" not in out

    def test_unchanged_behaviour_without_times(self):
        assert inject_section_summaries(ARTICLE, self.SUMS) == inject_section_summaries(
            ARTICLE, self.SUMS, times=None, video_id="A3_fG1h2a_g"
        )


# ---------- youtube_video_id ----------

class TestYoutubeVideoId:
    def test_common_url_forms(self):
        assert youtube_video_id("https://www.youtube.com/watch?v=A3_fG1h2a_g") == "A3_fG1h2a_g"
        assert youtube_video_id("https://www.youtube.com/watch?v=XUDkQA7cVWI&t=30s") == "XUDkQA7cVWI"
        assert youtube_video_id("https://youtu.be/4S25FfbFw4M") == "4S25FfbFw4M"

    def test_none_for_non_youtube(self):
        assert youtube_video_id("https://example.com") is None
        assert youtube_video_id("") is None
        assert youtube_video_id(None) is None


# ---------- generate_section_guide ----------

class TestGenerateSectionGuide:
    SEGMENTS = [seg(0, "intro talk"), seg(150, "breathing basics"), seg(1100, "thirteen minutes")]

    def _resp(self):
        return fake_response(json.dumps({"summaries": [
            {"heading": "Breathing Basics", "summary": "Breathe slowly.", "start": "02:30"},
            {"heading": "The 13-Minute Practice", "summary": "Do it daily.", "start": "18:20"},
        ]}))

    def test_one_request_returns_both_summaries_and_times(self):
        with patch("write_articles.client.models.generate_content", return_value=self._resp()) as call:
            sums, times = generate_section_guide(ARTICLE, segments=self.SEGMENTS)
        assert call.call_count == 1
        assert sums == {"Breathing Basics": "Breathe slowly.", "The 13-Minute Practice": "Do it daily."}
        assert times == {"Breathing Basics": 150, "The 13-Minute Practice": 1100}

    def test_the_transcript_goes_into_the_prompt(self):
        with patch("write_articles.client.models.generate_content", return_value=self._resp()) as call:
            generate_section_guide(ARTICLE, segments=self.SEGMENTS)
        prompt = call.call_args.kwargs["contents"]
        assert "[02:30] breathing basics" in prompt
        assert '"start"' in prompt

    def test_korean_prompt_also_carries_the_transcript(self):
        with patch("write_articles.client.models.generate_content", return_value=self._resp()) as call:
            generate_section_guide(ARTICLE, language="ko", segments=self.SEGMENTS)
        prompt = call.call_args.kwargs["contents"]
        assert "원본 영상 트랜스크립트" in prompt
        assert "[18:20] thirteen minutes" in prompt

    def test_without_segments_no_transcript_and_no_times(self):
        with patch("write_articles.client.models.generate_content", return_value=self._resp()) as call:
            sums, times = generate_section_guide(ARTICLE)
        assert "TRANSCRIPT" not in call.call_args.kwargs["contents"]
        assert times == {}
        assert len(sums) == 2

    def test_summaries_only_wrapper_is_unchanged(self):
        with patch("write_articles.client.models.generate_content", return_value=self._resp()):
            assert generate_section_summaries(ARTICLE) == {
                "Breathing Basics": "Breathe slowly.",
                "The 13-Minute Practice": "Do it daily.",
            }

    def test_api_failure_yields_empty_maps_not_an_exception(self):
        with patch("write_articles.client.models.generate_content", side_effect=RuntimeError("bad request")):
            assert generate_section_guide(ARTICLE, segments=self.SEGMENTS) == ({}, {})
