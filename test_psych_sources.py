"""
Tests for the psychology podcasts as an article source (psych_sources.py) and
the day's selection with psych slots (select_videos.select_daily_videos).
"""

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import psych_sources as ps
from listening import podcast_entry_id
from select_videos import select_daily_videos

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def entry(title, day, minutes=40, guid=None, audio=True, link="https://show.example/ep"):
    e = {
        "title": title,
        "id": guid or f"guid-{title}",
        "link": link,
        "summary": "<p>An episode about <b>envy</b> &amp; comparison.</p>",
        "published_parsed": time.strptime(day, "%Y-%m-%d"),
        "itunes_duration": str(minutes * 60),
    }
    if audio:
        e["enclosures"] = [{"href": f"https://cdn.example/{title.replace(' ', '-')}.mp3", "type": "audio/mpeg"}]
    return e


never = lambda _id: False  # noqa: E731


# ---------- reading the list and the feeds ----------

class TestReadFeeds:
    def test_url_and_name_in_order(self, tmp_path):
        f = tmp_path / "list.txt"
        f.write_text("# comment\n\nhttps://a.example/rss   # Show A\nhttps://b.example/rss\n", encoding="utf-8")
        assert ps.read_feeds(f) == [("https://a.example/rss", "Show A"), ("https://b.example/rss", "")]

    def test_the_shipped_list_is_the_13_janhyang_shows(self):
        feeds = ps.read_feeds()
        assert len(feeds) == 13
        assert feeds[0][1] == "Speaking of Psychology"
        # 잔향's On Purpose URL is really The Next Big Idea's feed
        assert ("https://feeds.megaphone.fm/on-purpose", "On Purpose with Jay Shetty") in feeds


class TestParseDuration:
    def test_formats(self):
        assert ps.parse_duration("5344") == 5344
        assert ps.parse_duration("1:29:04") == 5344
        assert ps.parse_duration("52:10") == 3130
        assert ps.parse_duration("") == 0
        assert ps.parse_duration("n/a") == 0


class TestEpisodeVideo:
    def test_shape(self):
        v = ps.episode_video(entry("Why We Envy", "2026-11-20"), "Speaking of Psychology")
        assert v["title"] == "Why We Envy"
        assert v["channel"] == "Speaking of Psychology"
        assert v["audio_url"].endswith(".mp3")
        assert v["url"] == "https://show.example/ep"
        assert v["published"] == "2026-11-20T00:00:00Z"
        assert v["duration"] == 2400
        assert (v["group"], v["source"]) == ("psych", "podcast")
        assert v["description"] == "An episode about envy & comparison."

    def test_id_matches_the_listening_edition(self):
        # processed_videos.json and Step 6 must call an episode the same thing
        e = entry("Why We Envy", "2026-11-20", guid="abc-123")
        v = ps.episode_video(e, "S")
        assert v["video_id"] == podcast_entry_id({"id": "abc-123", "audioUrl": v["audio_url"]})

    def test_no_audio_no_episode(self):
        assert ps.episode_video(entry("Trailer", "2026-11-20", audio=False), "S") is None


class TestPickEpisode:
    def test_newest_new_episode(self):
        entries = [entry("Older", "2026-11-20"), entry("Newer", "2026-11-22")]
        assert ps.pick_episode(entries, "S", never, now=NOW)["title"] == "Newer"

    def test_never_the_back_catalogue(self):
        # published before the list was copied from 잔향
        assert ps.pick_episode([entry("Old", "2026-11-18")], "S", never, now=NOW) is None

    def test_too_old_to_matter(self):
        later = datetime(2026, 12, 20, tzinfo=timezone.utc)
        assert ps.pick_episode([entry("Ep", "2026-11-20")], "S", never, now=later) is None

    def test_too_long_to_transcribe(self):
        assert ps.pick_episode([entry("Marathon", "2026-11-20", minutes=240)], "S", never, now=NOW) is None

    def test_processed_one_gives_way_to_the_next(self):
        entries = [entry("Done", "2026-11-22"), entry("Still new", "2026-11-21")]
        done = ps.episode_video(entries[0], "S")["video_id"]
        picked = ps.pick_episode(entries, "S", lambda i: i == done, now=NOW)
        assert picked["title"] == "Still new"


class TestFetchPsychEpisodes:
    def test_one_per_show_in_list_order_and_dead_feeds_skipped(self, tmp_path):
        f = tmp_path / "list.txt"
        f.write_text("https://a/rss # Show A\nhttps://dead/rss # Dead\nhttps://b/rss # Show B\n", encoding="utf-8")
        feeds = {
            "https://a/rss": {"entries": [entry("A1", "2026-11-21"), entry("A2", "2026-11-22")]},
            "https://b/rss": {"entries": [entry("B1", "2026-11-20")]},
        }
        out = ps.fetch_psych_episodes(f, fetch=feeds.get, is_processed=never, now=NOW)
        assert [(v["channel"], v["title"]) for v in out] == [("Show A", "A2"), ("Show B", "B1")]


class TestTranscriptStep:
    def test_podcast_episodes_are_transcribed_from_audio(self):
        from get_transcripts import get_transcripts_for_videos
        v = {"title": "Ep", "video_id": "pod-1", "audio_url": "https://cdn/x.mp3"}
        with patch("psych_sources.transcribe", return_value=("hello world", [{"start": 0.0, "text": "hello world"}])) as tr, \
             patch("get_transcripts.get_transcript") as yt:
            out = get_transcripts_for_videos([v])
        tr.assert_called_once()
        yt.assert_not_called()
        assert out[0]["transcript"] == "hello world"


# ---------- the day's selection ----------

def vid(title, group=""):
    return {"title": title, "channel": "C", "url": f"https://y/{title}", "group": group}


def labelled(*domains):
    rows = ", ".join(f'{{"index": {i}, "domain": "{d}"}}' for i, d in enumerate(domains))
    return SimpleNamespace(text=f'{{"videos": [{rows}]}}', usage_metadata=None, candidates=[])


def pick(videos, domains, limit=3, psych_limit=2):
    with patch("write_articles.client.models.generate_content", return_value=labelled(*domains)):
        return [v["title"] for v in select_daily_videos(videos, limit=limit, psych_limit=psych_limit)]


class TestSelectDailyVideos:
    def test_two_psych_and_one_other(self):
        videos = [vid("AI news"), vid("Election"), vid("Envy", "psych"), vid("Grief", "psych"), vid("Sleep", "psych")]
        assert pick(videos, ["technology", "politics", "health", "health", "health"]) == ["Envy", "Grief", "AI news"]

    def test_the_other_one_is_not_another_psychology_video(self):
        # A general channel's psychology video loses the third slot to a
        # different subject: the psych slots already cover health.
        videos = [vid("Gray Area on anxiety"), vid("Oil prices"), vid("Envy", "psych"), vid("Grief", "psych")]
        assert pick(videos, ["health", "business", "health", "health"]) == ["Envy", "Grief", "Oil prices"]

    def test_an_off_topic_episode_from_a_psych_show_competes_as_other(self):
        videos = [vid("Making Sense: the election", "psych"), vid("Envy", "psych"), vid("AI news")]
        assert pick(videos, ["politics", "health", "technology"], limit=2) == ["Envy", "Making Sense: the election"]

    def test_brain_science_counts_as_psychology(self):
        videos = [vid("AI news"), vid("Dopamine", "psych"), vid("Memory", "psych")]
        assert pick(videos, ["technology", "science", "health"]) == ["Dopamine", "Memory", "AI news"]

    def test_fewer_psych_episodes_leave_more_room_for_the_rest(self):
        videos = [vid("AI news"), vid("Election"), vid("Oil"), vid("Envy", "psych")]
        assert pick(videos, ["technology", "politics", "business", "health"]) == ["Envy", "AI news", "Election"]

    def test_psych_limit_holds_on_a_busy_day(self):
        videos = [vid("AI news"), vid("A", "psych"), vid("B", "psych"), vid("C", "psych")]
        assert pick(videos, ["technology", "health", "health", "health"]) == ["A", "B", "AI news"]

    def test_records_the_domain_for_categories(self):
        videos = [vid("AI news"), vid("Envy", "psych")]
        with patch("write_articles.client.models.generate_content", return_value=labelled("technology", "health")):
            select_daily_videos(videos, limit=1, psych_limit=1)
        assert [v["domain"] for v in videos] == ["technology", "health"]
