"""
Tests for video frame extraction + vision selection (Phase 3).

Pure-function tests only. yt-dlp download, ffmpeg, and the Gemini vision
call are exercised manually (live smoke), not here.
"""

import os
import pytest

from capture_frames import (
    frame_filename,
    build_ffmpeg_cmd,
    candidate_offsets,
    build_vision_prompt,
    parse_vision_choice,
    needs_capture,
    VISION_OFFSETS,
)


# ---------- frame_filename ----------

class TestFrameFilename:
    def test_basic(self):
        assert frame_filename("abc123", 90) == "abc123_01-30.jpg"

    def test_over_hour(self):
        assert frame_filename("abc123", 3725) == "abc123_1-02-05.jpg"

    def test_sanitizes_unsafe_chars(self):
        # Video IDs are normally safe, but defend against slashes/colons
        assert frame_filename("a/b:c", 5) == "a_b_c_00-05.jpg"

    def test_zero_seconds(self):
        assert frame_filename("v", 0) == "v_00-00.jpg"


# ---------- build_ffmpeg_cmd ----------

class TestBuildFfmpegCmd:
    def test_seek_before_input(self):
        cmd = build_ffmpeg_cmd("video.mp4", 42, "out.jpg")
        # -ss must precede -i for fast input seek
        ss_idx = cmd.index("-ss")
        i_idx = cmd.index("-i")
        assert ss_idx < i_idx
        assert cmd[ss_idx + 1] == "42"
        assert cmd[i_idx + 1] == "video.mp4"

    def test_single_frame_and_overwrite(self):
        cmd = build_ffmpeg_cmd("v.mp4", 1, "o.jpg")
        assert "-frames:v" in cmd
        assert cmd[cmd.index("-frames:v") + 1] == "1"
        assert "-y" in cmd
        assert cmd[-1] == "o.jpg"

    def test_starts_with_ffmpeg(self):
        assert build_ffmpeg_cmd("v.mp4", 1, "o.jpg")[0] == "ffmpeg"


# ---------- candidate_offsets ----------

class TestCandidateOffsets:
    def test_applies_vision_offsets(self):
        offs = candidate_offsets(100, duration=300)
        expected = sorted({100 + o for o in VISION_OFFSETS})
        assert offs == expected

    def test_clamps_negative(self):
        # near the start, negative candidates are dropped
        offs = candidate_offsets(1, duration=300)
        assert all(o >= 0 for o in offs)
        assert 1 in offs  # the exact moment always survives

    def test_clamps_past_duration(self):
        offs = candidate_offsets(298, duration=300)
        assert all(o <= 300 for o in offs)

    def test_none_duration_no_upper_clamp(self):
        offs = candidate_offsets(100, duration=None)
        assert max(offs) == 100 + max(VISION_OFFSETS)

    def test_always_includes_exact_moment(self):
        # even if every offset clamps away, the moment itself remains
        offs = candidate_offsets(0, duration=0)
        assert offs == [0]

    def test_dedupes(self):
        offs = candidate_offsets(100, duration=300)
        assert len(offs) == len(set(offs))


# ---------- build_vision_prompt ----------

class TestBuildVisionPrompt:
    def test_includes_caption_and_count(self):
        p = build_vision_prompt("A bar chart of sleep loss", n=4)
        assert "A bar chart of sleep loss" in p
        assert "4" in p
        assert "JSON" in p
        # must allow a "none are good" answer
        assert "-1" in p

    def test_mentions_zero_based_index(self):
        p = build_vision_prompt("cap", n=3)
        assert "index" in p.lower()


# ---------- parse_vision_choice ----------

class TestParseVisionChoice:
    def test_valid_index(self):
        assert parse_vision_choice('{"index": 2, "reason": "clear chart"}', n=4) == 2

    def test_code_fenced(self):
        assert parse_vision_choice('```json\n{"index": 0}\n```', n=4) == 0

    def test_minus_one_returns_none(self):
        assert parse_vision_choice('{"index": -1}', n=4) is None

    def test_out_of_range_returns_none(self):
        assert parse_vision_choice('{"index": 9}', n=4) is None

    def test_garbage_returns_none(self):
        assert parse_vision_choice("not json at all", n=4) is None
        assert parse_vision_choice("", n=4) is None

    def test_bare_integer(self):
        # tolerate a model that returns just a number
        assert parse_vision_choice("2", n=4) == 2


# ---------- needs_capture ----------

class TestNeedsCapture:
    def test_missing_file(self, tmp_path):
        assert needs_capture(str(tmp_path / "nope.jpg")) is True

    def test_zero_byte_file(self, tmp_path):
        p = tmp_path / "empty.jpg"
        p.write_bytes(b"")
        assert needs_capture(str(p)) is True

    def test_existing_nonempty_file(self, tmp_path):
        p = tmp_path / "ok.jpg"
        p.write_bytes(b"\xff\xd8\xff")  # jpeg magic
        assert needs_capture(str(p)) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
