"""
Tests for the tech-first video curation step (Step 1c).

Pure-function tests plus the ranking path with a mocked Gemini client — the
selection must stay deterministic and must never drop the whole digest when
the API is unavailable.
"""

from types import SimpleNamespace
from unittest.mock import patch

from select_videos import (
    parse_scores,
    _heuristic_score,
    score_videos,
    select_tech_videos,
)


def vid(title, channel="Some Channel"):
    return {"title": title, "channel": channel, "url": f"https://y/{title[:5]}"}


def fake_response(payload):
    return SimpleNamespace(text=payload, usage_metadata=None, candidates=[])


# ---------- parse_scores ----------

class TestParseScores:
    def test_reads_index_score_and_reason(self):
        out = parse_scores('{"scores":[{"index":0,"score":91,"why":"AI research"}]}', 2)
        assert out == {0: (91.0, "AI research")}

    def test_accepts_a_bare_array(self):
        assert parse_scores('[{"index":1,"score":40}]', 2) == {1: (40.0, "")}

    def test_drops_out_of_range_indexes(self):
        # A hallucinated row must not shift the ranking off the video list.
        out = parse_scores('{"scores":[{"index":0,"score":90},{"index":9,"score":95}]}', 2)
        assert out == {0: (90.0, "")}

    def test_drops_rows_with_unusable_numbers(self):
        out = parse_scores('{"scores":[{"index":"x","score":9},{"index":1,"score":"hi"}]}', 3)
        assert out == {}

    def test_returns_empty_on_junk(self):
        assert parse_scores("not json", 2) == {}
        assert parse_scores("", 2) == {}


# ---------- _heuristic_score ----------

class TestHeuristicScore:
    def test_ai_titles_outrank_everything(self):
        assert _heuristic_score(vid("What GPT-5 means for coding")) == 95

    def test_general_tech_beats_science(self):
        assert _heuristic_score(vid("Inside a semiconductor fab")) > _heuristic_score(
            vid("A new study on the brain")
        )

    def test_politics_and_economics_score_lowest(self):
        assert _heuristic_score(vid("The war in Ukraine, explained")) == 5
        assert _heuristic_score(vid("Why inflation won't go away")) == 5

    def test_unknown_topics_land_between_politics_and_science(self):
        score = _heuristic_score(vid("A conversation with my grandmother"))
        assert 5 < score < 55


# ---------- score_videos ----------

class TestScoreVideos:
    def test_uses_model_scores_when_available(self):
        videos = [vid("AI agents"), vid("Election night")]
        resp = fake_response('{"scores":[{"index":0,"score":97,"why":"AI"},{"index":1,"score":2,"why":"politics"}]}')
        with patch("write_articles.client.models.generate_content", return_value=resp):
            out = score_videos(videos)
        assert [s for _, s, _ in out] == [97.0, 2.0]

    def test_falls_back_per_video_when_a_score_is_missing(self):
        videos = [vid("AI agents"), vid("The war in Ukraine, explained")]
        resp = fake_response('{"scores":[{"index":0,"score":97,"why":"AI"}]}')
        with patch("write_articles.client.models.generate_content", return_value=resp):
            out = score_videos(videos)
        assert out[0][1] == 97.0
        assert out[1][1] == 5  # heuristic
        assert out[1][2] == "keyword fallback"

    def test_api_failure_falls_back_to_keywords_for_all(self):
        videos = [vid("GPT-5 and the future of work"), vid("Why oil prices spiked")]
        with patch("write_articles.client.models.generate_content", side_effect=RuntimeError("429")):
            out = score_videos(videos)
        assert [s for _, s, _ in out] == [95, 5]

    def test_empty_input(self):
        assert score_videos([]) == []


# ---------- select_tech_videos ----------

class TestSelectTechVideos:
    def test_keeps_the_highest_scoring_videos_best_first(self):
        videos = [vid("Election night"), vid("AI agents"), vid("Robotics lab tour")]
        resp = fake_response(
            '{"scores":[{"index":0,"score":3},{"index":1,"score":98},{"index":2,"score":80}]}'
        )
        with patch("write_articles.client.models.generate_content", return_value=resp):
            kept = select_tech_videos(videos, limit=2)
        assert [v["title"] for v in kept] == ["AI agents", "Robotics lab tour"]

    def test_drops_below_floor_rather_than_filling_the_cap(self):
        # The real failure this guards: one strong tech video and a quiet day.
        # Filling to `limit` would backfill the digest with a culture piece.
        videos = [vid("AI agents"), vid("Hollywood and abortion"), vid("A war explained")]
        resp = fake_response(
            '{"scores":[{"index":0,"score":95},{"index":1,"score":15},{"index":2,"score":5}]}'
        )
        with patch("write_articles.client.models.generate_content", return_value=resp):
            kept = select_tech_videos(videos, limit=4, min_score=40)
        assert [v["title"] for v in kept] == ["AI agents"]

    def test_applies_the_floor_even_when_under_the_cap(self):
        videos = [vid("AI agents"), vid("Election night")]
        resp = fake_response('{"scores":[{"index":0,"score":95},{"index":1,"score":4}]}')
        with patch("write_articles.client.models.generate_content", return_value=resp):
            kept = select_tech_videos(videos, limit=4, min_score=40)
        assert [v["title"] for v in kept] == ["AI agents"]

    def test_keeps_the_best_one_when_nothing_clears_the_floor(self):
        # An empty digest also empties the speaking prompt and reading feed.
        videos = [vid("Election night"), vid("Oil prices")]
        resp = fake_response('{"scores":[{"index":0,"score":8},{"index":1,"score":3}]}')
        with patch("write_articles.client.models.generate_content", return_value=resp):
            kept = select_tech_videos(videos, limit=4, min_score=40)
        assert [v["title"] for v in kept] == ["Election night"]

    def test_ties_break_toward_the_earlier_video(self):
        videos = [vid("First"), vid("Second"), vid("Third")]
        resp = fake_response(
            '{"scores":[{"index":0,"score":50},{"index":1,"score":50},{"index":2,"score":50}]}'
        )
        with patch("write_articles.client.models.generate_content", return_value=resp):
            kept = select_tech_videos(videos, limit=2)
        assert [v["title"] for v in kept] == ["First", "Second"]

    def test_a_single_video_skips_the_api_call(self):
        videos = [vid("Anything at all")]
        with patch("write_articles.client.models.generate_content") as call:
            assert select_tech_videos(videos) == videos
        call.assert_not_called()

    def test_never_returns_empty_when_the_api_is_down(self):
        videos = [vid("GPT-5 explained"), vid("Robotics"), vid("Oil prices")]
        with patch("write_articles.client.models.generate_content", side_effect=RuntimeError("down")):
            kept = select_tech_videos(videos, limit=2, min_score=40)
        assert [v["title"] for v in kept] == ["GPT-5 explained", "Robotics"]

    def test_limit_of_zero_or_less_keeps_everything(self):
        videos = [vid("A"), vid("B")]
        assert select_tech_videos(videos, limit=0) == videos
