"""
Tests for frame-moment selection + marker injection (Phase 2).

Pure-function tests only. The live Gemini call (select_frame_moments) is
exercised separately with a mocked client.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from write_articles import (
    build_frame_prompt,
    parse_frame_moments,
    clamp_and_dedupe,
    inject_frame_markers,
    _mmss_to_seconds,
    select_frame_moments,
)


# ---------- _mmss_to_seconds ----------

class TestMmssToSeconds:
    def test_mm_ss(self):
        assert _mmss_to_seconds("01:30") == 90
        assert _mmss_to_seconds("00:05") == 5

    def test_h_mm_ss(self):
        assert _mmss_to_seconds("1:02:05") == 3725

    def test_plain_int_string(self):
        assert _mmss_to_seconds("90") == 90

    def test_garbage_returns_none(self):
        assert _mmss_to_seconds("abc") is None
        assert _mmss_to_seconds("") is None


# ---------- build_frame_prompt ----------

class TestBuildFramePrompt:
    def test_includes_count_and_constraints(self):
        p = build_frame_prompt("ARTICLE BODY", "[00:10] hello\n[01:00] world", n=4)
        assert "4" in p
        # JSON-only instruction
        assert "JSON" in p
        # anti talking-head guidance present
        assert "talking head" in p.lower() or "talking-head" in p.lower()
        # both inputs embedded
        assert "ARTICLE BODY" in p
        assert "[01:00] world" in p

    def test_requires_anchor_and_caption_fields(self):
        p = build_frame_prompt("a", "b", n=3)
        assert "caption" in p
        assert "anchor" in p
        assert "timestamp" in p


# ---------- parse_frame_moments ----------

VALID_JSON = """[
  {"timestamp": "01:30", "caption": "A diagram of the sleep cycle", "anchor": "the sleep cycle has four stages"},
  {"timestamp": "03:00", "caption": "Speaker shows a brain scan", "anchor": "fMRI scans revealed"}
]"""


class TestParseFrameMoments:
    def test_clean_json(self):
        out = parse_frame_moments(VALID_JSON)
        assert len(out) == 2
        assert out[0]["seconds"] == 90
        assert out[0]["caption"].startswith("A diagram")
        assert out[0]["anchor"] == "the sleep cycle has four stages"

    def test_code_fenced_json(self):
        fenced = "```json\n" + VALID_JSON + "\n```"
        out = parse_frame_moments(fenced)
        assert len(out) == 2

    def test_drops_items_missing_required_fields(self):
        text = '[{"timestamp":"01:00"}, {"caption":"no ts","anchor":"x"}]'
        out = parse_frame_moments(text)
        # neither item is complete (first lacks caption, second lacks timestamp)
        assert out == []

    def test_truncated_json_salvaged(self):
        truncated = (
            '[{"timestamp":"01:30","caption":"first one here","anchor":"alpha"},'
            '{"timestamp":"02:30","caption":"second one cut off ne'
        )
        out = parse_frame_moments(truncated)
        # At least the first complete object survives
        assert len(out) >= 1
        assert out[0]["seconds"] == 90

    def test_bad_timestamp_item_dropped(self):
        text = '[{"timestamp":"xx:yy","caption":"c","anchor":"a"}]'
        assert parse_frame_moments(text) == []


# ---------- clamp_and_dedupe ----------

class TestClampAndDedupe:
    def _m(self, secs, cap="c", anc="a"):
        return {"seconds": secs, "timestamp": "x", "caption": cap, "anchor": anc}

    def test_sorts_by_seconds(self):
        out = clamp_and_dedupe([self._m(120), self._m(30), self._m(80)], duration=300)
        assert [m["seconds"] for m in out] == [30, 80, 120]

    def test_removes_out_of_range(self):
        out = clamp_and_dedupe([self._m(50), self._m(9999), self._m(-5)], duration=300)
        assert [m["seconds"] for m in out] == [50]

    def test_dedupes_near_duplicates(self):
        # 50 and 53 are within min_gap=5 -> keep first only
        out = clamp_and_dedupe([self._m(50), self._m(53), self._m(200)], duration=300, min_gap=5)
        assert [m["seconds"] for m in out] == [50, 200]

    def test_caps_at_max_n(self):
        moments = [self._m(s) for s in (10, 40, 70, 100, 130, 160)]
        out = clamp_and_dedupe(moments, duration=300, max_n=4, min_gap=5)
        assert len(out) == 4

    def test_no_duration_skips_upper_clamp(self):
        out = clamp_and_dedupe([self._m(10), self._m(9999)], duration=None)
        assert [m["seconds"] for m in out] == [10, 9999]


# ---------- inject_frame_markers ----------

class TestInjectFrameMarkers:
    def test_marker_inserted_after_anchor_paragraph(self):
        article = (
            "# Title\n\n"
            "Intro paragraph about the sleep cycle has four stages of rest.\n\n"
            "Another paragraph about something else.\n"
        )
        moments = [{"seconds": 90, "timestamp": "01:30",
                    "caption": "cap", "anchor": "the sleep cycle has four stages"}]
        out = inject_frame_markers(article, moments)
        assert "[[FRAME:90]]" in out
        # Marker must come after the anchor paragraph, before the next one
        anchor_pos = out.find("four stages of rest")
        marker_pos = out.find("[[FRAME:90]]")
        next_para = out.find("Another paragraph")
        assert anchor_pos < marker_pos < next_para

    def test_anchor_not_found_appends_at_end(self):
        article = "# Title\n\nSome body text.\n"
        moments = [{"seconds": 42, "timestamp": "00:42",
                    "caption": "cap", "anchor": "nonexistent phrase zzz"}]
        out = inject_frame_markers(article, moments)
        assert "[[FRAME:42]]" in out
        # appended after the original content
        assert out.find("Some body text") < out.find("[[FRAME:42]]")

    def test_multiple_markers(self):
        article = (
            "# T\n\nFirst about alpha topic here.\n\n"
            "Second about beta topic here.\n"
        )
        moments = [
            {"seconds": 10, "timestamp": "00:10", "caption": "c1", "anchor": "alpha topic"},
            {"seconds": 60, "timestamp": "01:00", "caption": "c2", "anchor": "beta topic"},
        ]
        out = inject_frame_markers(article, moments)
        assert "[[FRAME:10]]" in out
        assert "[[FRAME:60]]" in out
        assert out.find("[[FRAME:10]]") < out.find("[[FRAME:60]]")

    def test_empty_moments_returns_article_unchanged(self):
        article = "# T\n\nBody.\n"
        assert inject_frame_markers(article, []) == article


# ---------- select_frame_moments (mocked Gemini) ----------

def _mock_resp(text):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=100, candidates_token_count=80, thoughts_token_count=0
        ),
    )


class TestSelectFrameMoments:
    def test_returns_clamped_moments(self):
        video = {
            "title": "T", "channel": "C",
            "transcript_segments": [{"start": 90, "text": "the sleep cycle"}],
            "duration": 300,
        }
        article = "# H\n\nthe sleep cycle has four stages.\n"
        with patch("write_articles.client") as mock_client, \
             patch("write_articles.time.sleep"):
            mock_client.models.generate_content.return_value = _mock_resp(VALID_JSON)
            moments = select_frame_moments(video, article, n=4)
            assert len(moments) == 2
            assert moments[0]["seconds"] == 90
            # thinking disabled like the other extraction calls
            cfg = mock_client.models.generate_content.call_args.kwargs["config"]
            tc = getattr(cfg, "thinking_config", None)
            assert tc is not None and getattr(tc, "thinking_budget", None) == 0

    def test_no_segments_returns_empty_without_api_call(self):
        video = {"title": "T", "channel": "C", "transcript_segments": []}
        with patch("write_articles.client") as mock_client:
            moments = select_frame_moments(video, "article", n=4)
            assert moments == []
            mock_client.models.generate_content.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
