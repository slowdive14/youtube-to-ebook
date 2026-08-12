"""
Tests for the daily video curation step (Step 1c).

Selection is by subject spread, not topic preference. Pure-function tests plus
the classification path with a mocked Gemini client — the pick must stay
deterministic and must never drop the whole digest when the API is down.
"""

from types import SimpleNamespace
from unittest.mock import patch

from select_videos import (
    parse_domains,
    _heuristic_domain,
    classify_videos,
    select_diverse_videos,
)


def vid(title, channel="Some Channel"):
    return {"title": title, "channel": channel, "url": f"https://y/{title[:5]}"}


def fake_response(payload):
    return SimpleNamespace(text=payload, usage_metadata=None, candidates=[])


def domains_json(*domains):
    rows = ", ".join(
        f'{{"index": {i}, "domain": "{d}"}}' for i, d in enumerate(domains)
    )
    return f'{{"videos": [{rows}]}}'


# ---------- parse_domains ----------

class TestParseDomains:
    def test_reads_index_and_domain(self):
        assert parse_domains(domains_json("technology", "culture"), 2) == {
            0: "technology",
            1: "culture",
        }

    def test_accepts_a_bare_array(self):
        assert parse_domains('[{"index":1,"domain":"health"}]', 2) == {1: "health"}

    def test_drops_labels_outside_the_known_set(self):
        out = parse_domains('{"videos":[{"index":0,"domain":"sports"},{"index":1,"domain":"science"}]}', 2)
        assert out == {1: "science"}

    def test_drops_out_of_range_indexes(self):
        out = parse_domains('{"videos":[{"index":0,"domain":"science"},{"index":9,"domain":"culture"}]}', 2)
        assert out == {0: "science"}

    def test_is_case_insensitive(self):
        assert parse_domains('{"videos":[{"index":0,"domain":"Technology"}]}', 1) == {0: "technology"}

    def test_returns_empty_on_junk(self):
        assert parse_domains("not json", 2) == {}
        assert parse_domains("", 2) == {}


# ---------- _heuristic_domain ----------

class TestHeuristicDomain:
    def test_recognizes_each_area(self):
        assert _heuristic_domain(vid("What GPT-5 means for coding")) == "technology"
        assert _heuristic_domain(vid("A new quantum physics result")) == "science"
        assert _heuristic_domain(vid("How sleep rebuilds your brain")) == "health"
        assert _heuristic_domain(vid("Why inflation won't go away")) == "business"
        assert _heuristic_domain(vid("The war in Ukraine, explained")) == "politics"
        assert _heuristic_domain(vid("The history of jazz music")) == "culture"

    def test_unknown_topics_fall_back_to_other(self):
        assert _heuristic_domain(vid("A quiet afternoon")) == "other"


# ---------- classify_videos ----------

class TestClassifyVideos:
    def test_uses_model_labels(self):
        videos = [vid("AI agents"), vid("Election night")]
        with patch("write_articles.client.models.generate_content",
                   return_value=fake_response(domains_json("technology", "politics"))):
            assert [d for _, d in classify_videos(videos)] == ["technology", "politics"]

    def test_falls_back_per_video_for_a_missing_label(self):
        videos = [vid("AI agents"), vid("The war in Ukraine, explained")]
        with patch("write_articles.client.models.generate_content",
                   return_value=fake_response('{"videos":[{"index":0,"domain":"technology"}]}')):
            assert [d for _, d in classify_videos(videos)] == ["technology", "politics"]

    def test_api_failure_falls_back_to_keywords_for_all(self):
        videos = [vid("GPT-5 explained"), vid("Why oil prices spiked")]
        with patch("write_articles.client.models.generate_content", side_effect=RuntimeError("429")):
            assert [d for _, d in classify_videos(videos)] == ["technology", "business"]

    def test_empty_input(self):
        assert classify_videos([]) == []


# ---------- select_diverse_videos ----------

class TestSelectDiverseVideos:
    def test_takes_one_per_subject_area(self):
        videos = [vid("AI agents"), vid("More AI news"), vid("A jazz history"), vid("Sleep study")]
        with patch("write_articles.client.models.generate_content",
                   return_value=fake_response(domains_json("technology", "technology", "culture", "health"))):
            kept = select_diverse_videos(videos, limit=3)
        assert [v["title"] for v in kept] == ["AI agents", "A jazz history", "Sleep study"]

    def test_prefers_spread_over_the_channel_order(self):
        # The second video would win on order alone; it loses because its
        # subject is already covered.
        videos = [vid("Chip war"), vid("Chip war part 2"), vid("An election")]
        with patch("write_articles.client.models.generate_content",
                   return_value=fake_response(domains_json("technology", "technology", "politics"))):
            kept = select_diverse_videos(videos, limit=2)
        assert [v["title"] for v in kept] == ["Chip war", "An election"]

    def test_tops_up_from_one_area_when_there_are_not_enough(self):
        videos = [vid("AI one"), vid("AI two"), vid("AI three"), vid("AI four")]
        with patch("write_articles.client.models.generate_content",
                   return_value=fake_response(domains_json(*["technology"] * 4))):
            kept = select_diverse_videos(videos, limit=3)
        assert [v["title"] for v in kept] == ["AI one", "AI two", "AI three"]

    def test_no_topic_is_privileged(self):
        # Politics and business used to be scored down to 5 and dropped; now a
        # day of them is a perfectly good day.
        videos = [vid("An election"), vid("Oil prices"), vid("A protest"), vid("AI agents")]
        with patch("write_articles.client.models.generate_content",
                   return_value=fake_response(domains_json("politics", "business", "politics", "technology"))):
            kept = select_diverse_videos(videos, limit=3)
        assert [v["title"] for v in kept] == ["An election", "Oil prices", "AI agents"]

    def test_skips_the_api_call_when_nothing_would_be_dropped(self):
        videos = [vid("A"), vid("B")]
        with patch("write_articles.client.models.generate_content") as call:
            assert select_diverse_videos(videos, limit=3) == videos
        call.assert_not_called()

    def test_still_returns_a_full_day_when_the_api_is_down(self):
        videos = [vid("GPT-5 explained"), vid("Oil prices spiked"), vid("A sleep study"), vid("An election")]
        with patch("write_articles.client.models.generate_content", side_effect=RuntimeError("down")):
            kept = select_diverse_videos(videos, limit=3)
        assert len(kept) == 3

    def test_limit_of_zero_or_less_keeps_everything(self):
        videos = [vid("A"), vid("B")]
        assert select_diverse_videos(videos, limit=0) == videos

    def test_empty_input(self):
        assert select_diverse_videos([], limit=3) == []
