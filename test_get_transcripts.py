"""
Tests for transcript timestamp helpers (Phase 1 of video-frame-capture).

Pure-function tests only — the live YouTube API call is not exercised here.
"""

import pytest

from get_transcripts import seconds_to_mmss, format_segments_with_timestamps


class TestSecondsToMmss:
    def test_under_a_minute(self):
        assert seconds_to_mmss(5) == "00:05"
        assert seconds_to_mmss(0) == "00:00"

    def test_minutes_and_seconds(self):
        assert seconds_to_mmss(90) == "01:30"
        assert seconds_to_mmss(599) == "09:59"

    def test_over_an_hour_uses_h_mm_ss(self):
        assert seconds_to_mmss(3725) == "1:02:05"
        assert seconds_to_mmss(3600) == "1:00:00"

    def test_floats_are_floored(self):
        assert seconds_to_mmss(90.9) == "01:30"

    def test_negative_clamped_to_zero(self):
        assert seconds_to_mmss(-3) == "00:00"


class TestFormatSegmentsWithTimestamps:
    def test_basic_lines(self):
        segments = [
            {"start": 0, "text": "Hello everyone"},
            {"start": 90, "text": "today we talk about sleep"},
        ]
        out = format_segments_with_timestamps(segments)
        assert out == "[00:00] Hello everyone\n[01:30] today we talk about sleep"

    def test_empty_segments_returns_empty_string(self):
        assert format_segments_with_timestamps([]) == ""

    def test_skips_blank_text(self):
        segments = [
            {"start": 0, "text": "  "},
            {"start": 10, "text": "real line"},
        ]
        out = format_segments_with_timestamps(segments)
        assert out == "[00:10] real line"

    def test_strips_whitespace_in_text(self):
        segments = [{"start": 5, "text": "  spaced  "}]
        assert format_segments_with_timestamps(segments) == "[00:05] spaced"

    def test_tolerates_missing_keys(self):
        # Defensive: a malformed segment without start/text shouldn't crash
        segments = [{"text": "no start"}, {"start": 12}]
        out = format_segments_with_timestamps(segments)
        # 'no start' defaults to 0s; the start-only entry has no text -> skipped
        assert out == "[00:00] no start"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
