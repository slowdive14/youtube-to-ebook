"""
Tests for the listening edition (listening.py): matching a video to its
podcast episode, cleaning the model's timed transcript, and publishing.
Network and Gemini are never touched — lookups and transcription are patched.
"""

import json
from unittest.mock import patch

import listening
from listening import (
    normalize_title,
    title_similarity,
    pick_episode,
    clock_to_seconds,
    clean_segments,
    save_entries,
    make_listening_entries,
)


def result(title, date="2026-10-12T10:00:00Z", url="https://cdn.example.com/a.mp3", show="It's Been a Minute"):
    return {
        "trackName": title,
        "releaseDate": date,
        "episodeUrl": url,
        "collectionName": show,
        "trackTimeMillis": 26 * 60 * 1000,
        "artworkUrl600": "https://img.example.com/a.jpg",
    }


# --- matching ---------------------------------------------------------------

def test_titles_match_across_quotes_dashes_and_episode_numbers():
    assert normalize_title("#702 - The Proposal: to know less?") == "the proposal to know less"
    assert title_similarity("It’s here", "It's here") == 1.0


def test_picks_the_episode_with_the_same_title_and_date():
    ep = pick_episode(
        [result("Something else entirely"), result("The proposal to know less about America")],
        "The proposal to know less about America",
        "2026-10-12T05:00:00Z",
    )
    assert ep["audioUrl"] == "https://cdn.example.com/a.mp3"
    assert ep["show"] == "It's Been a Minute"
    assert ep["duration"] == 26 * 60


def test_rejects_a_same_titled_episode_from_another_time():
    # Reruns and generic titles collide: the date has to agree too.
    assert pick_episode(
        [result("The proposal to know less about America", date="2018-10-22T10:00:00Z")],
        "The proposal to know less about America",
        "2026-10-12T05:00:00Z",
    ) is None


def test_without_a_video_date_only_recent_episodes_count():
    old = result("Weekly news roundup", date="2020-01-01T00:00:00Z")
    assert pick_episode([old], "Weekly news roundup", None) is None


def test_rejects_a_loose_title_match():
    assert pick_episode([result("The proposal")], "The proposal to know less about America", "2026-10-12") is None


# --- transcript cleaning ----------------------------------------------------

def test_reads_every_clock_format():
    assert clock_to_seconds("0:15") == 15
    assert clock_to_seconds("1:02:03") == 3723
    assert clock_to_seconds("95") == 95
    assert clock_to_seconds("soon") is None


def test_segments_get_absolute_times_and_keep_ads_flagged():
    raw = [
        {"start": "0:00", "en": "Hey, Lulu here.", "ko": "룰루입니다.", "ad": True, "speaker": "Host"},
        {"start": "0:15", "en": "What is a question?", "ko": "질문이 뭔가요?", "ad": False},
    ]
    out = clean_segments(raw, offset=2400)
    assert out == [
        {"start": 2400.0, "en": "Hey, Lulu here.", "ko": "룰루입니다.", "speaker": "Host", "ad": True},
        {"start": 2415.0, "en": "What is a question?", "ko": "질문이 뭔가요?"},
    ]


def test_drops_times_that_run_backwards_or_past_the_chunk():
    raw = [
        {"start": "1:00", "en": "one", "ko": ""},
        {"start": "0:30", "en": "backwards", "ko": ""},
        {"start": "50:00", "en": "past the end", "ko": ""},
        {"start": "1:20", "en": "two", "ko": ""},
        {"start": "nonsense", "en": "no time", "ko": ""},
        {"start": "1:40", "en": "", "ko": "no text"},
    ]
    assert [s["en"] for s in clean_segments(raw, limit=40 * 60)] == ["one", "two"]


# --- publishing -------------------------------------------------------------

def entry(vid):
    return {"id": vid, "title": vid, "audioUrl": "a", "segments": [{"start": 0, "en": "x", "ko": "y"}]}


def test_saves_one_file_per_episode_and_prunes_the_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(listening, "KEEP_EPISODES", 2)
    import os, time
    folder = tmp_path / "src" / "content" / "listening"
    folder.mkdir(parents=True)
    for i, vid in enumerate(["old1", "old2"]):
        p = folder / f"{vid}.json"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (time.time() - 1000 + i, time.time() - 1000 + i))

    written, removed = save_entries([entry("new1")], tmp_path)

    assert [p.name for p in written] == ["new1.json"]
    assert [p.name for p in removed] == ["old1.json"]
    assert json.loads((folder / "new1.json").read_text(encoding="utf-8"))["segments"][0]["ko"] == "y"


def video(vid, title="An episode"):
    return {"title": title, "url": f"https://www.youtube.com/watch?v={vid}", "channel": "NPR Podcasts"}


EPISODE = {
    "audioUrl": "https://cdn.example.com/a.mp3",
    "show": "It's Been a Minute",
    "episodeTitle": "An episode",
    "duration": 1560,
    "imageUrl": "",
    "releaseDate": "2026-10-12T10:00:00Z",
}
SEGMENTS = [{"start": float(i * 10), "en": f"line {i}", "ko": f"줄 {i}"} for i in range(8)]


def test_transcribes_podcast_episodes_and_skips_video_only_ones(tmp_path):
    lookups = {"Podcast one": EPISODE, "Video only": None, "Podcast two": EPISODE}
    with patch.object(listening, "find_podcast_episode", side_effect=lambda t, p=None: lookups[t]), \
         patch.object(listening, "transcribe_episode", return_value=(SEGMENTS, 1560)) as tr:
        out = make_listening_entries(
            [video("AAAAAAAAAA1", "Podcast one"), video("AAAAAAAAAA2", "Video only"), video("AAAAAAAAAA3", "Podcast two")],
            client=object(), repo_path=tmp_path, limit=2,
        )
    assert [e["id"] for e in out] == ["AAAAAAAAAA1", "AAAAAAAAAA3"]
    assert tr.call_count == 2
    assert out[0]["audioUrl"] == EPISODE["audioUrl"] and out[0]["segments"] == SEGMENTS


def test_stops_at_the_daily_limit_and_never_redoes_an_episode(tmp_path):
    folder = tmp_path / "src" / "content" / "listening"
    folder.mkdir(parents=True)
    (folder / "AAAAAAAAAA1.json").write_text("{}", encoding="utf-8")
    with patch.object(listening, "find_podcast_episode", return_value=EPISODE) as find, \
         patch.object(listening, "transcribe_episode", return_value=(SEGMENTS, 1560)):
        out = make_listening_entries(
            [video("AAAAAAAAAA1"), video("AAAAAAAAAA2"), video("AAAAAAAAAA3")],
            client=object(), repo_path=tmp_path, limit=1,
        )
    assert [e["id"] for e in out] == ["AAAAAAAAAA2"]
    assert find.call_count == 1  # the done one wasn't even looked up


# --- followed podcasts (Step 6) ---------------------------------------------

from datetime import datetime, timedelta, timezone

from listening import (
    read_podcast_list,
    podcast_entry_id,
    pick_feed_episode,
    make_podcast_entries,
)

NOW = datetime.now(timezone.utc)


def ep(guid, days_ago=1, minutes=30, audio=None):
    return {
        "id": guid,
        "title": f"Episode {guid}",
        "audioUrl": audio or f"https://cdn.example.com/{guid}.mp3",
        "duration": minutes * 60,
        "publishedAt": (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z"),
    }


def feed(title, *episodes):
    return {"title": title, "author": f"{title} host", "imageUrl": "", "episodes": list(episodes)}


def test_reads_the_podcast_list_ignoring_notes_and_blanks(tmp_path):
    p = tmp_path / "podcasts.txt"
    p.write_text("# heading\n\nhttps://a.example.com/rss   # Show A\nnot a url\nhttps://b.example.com/rss\n", encoding="utf-8")
    assert read_podcast_list(p) == ["https://a.example.com/rss", "https://b.example.com/rss"]


def test_episode_ids_are_stable_and_filename_safe():
    a = podcast_entry_id({"id": "tag:megaphone/abc:123?x=1"})
    assert a == podcast_entry_id({"id": "tag:megaphone/abc:123?x=1"})
    assert a.startswith("pod-") and a.replace("-", "").isalnum()


def test_picks_the_newest_recent_episode_within_the_length_limit(tmp_path):
    f = feed("Show", ep("long", 1, minutes=180), ep("ok", 2, minutes=45), ep("older", 3, minutes=30))
    assert pick_feed_episode(f, tmp_path)["id"] == "ok"


def test_ignores_old_and_already_done_episodes(tmp_path):
    folder = tmp_path / "src" / "content" / "listening"
    folder.mkdir(parents=True)
    (folder / f"{podcast_entry_id({'id': 'done'})}.json").write_text("{}", encoding="utf-8")
    f = feed("Show", ep("done", 1), ep("stale", 30))
    assert pick_feed_episode(f, tmp_path) is None


def write_done(tmp_path, show, added):
    folder = tmp_path / "src" / "content" / "listening"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{show}.json").write_text(json.dumps({"show": show, "addedAt": added}), encoding="utf-8")


def test_shows_take_turns_starting_with_the_longest_unserved(tmp_path):
    write_done(tmp_path, "Culips", "2026-10-12")  # served yesterday
    feeds = {"a": feed("Culips", ep("c1")), "b": feed("Hidden Brain", ep("h1"))}
    with patch.object(listening, "transcribe_episode", return_value=(SEGMENTS, 1800)):
        out = make_podcast_entries(tmp_path, client=object(), limit=1, feeds=["a", "b"], fetch=feeds.get)
    assert [e["show"] for e in out] == ["Hidden Brain"]
    assert out[0]["videoUrl"] == "" and out[0]["audioUrl"] == "https://cdn.example.com/h1.mp3"


def test_a_show_with_nothing_new_passes_its_turn(tmp_path):
    feeds = {"a": feed("Quiet", ep("q", 40)), "b": feed("Busy", ep("b1"))}
    with patch.object(listening, "transcribe_episode", return_value=(SEGMENTS, 1800)) as tr:
        out = make_podcast_entries(tmp_path, client=object(), limit=1, feeds=["a", "b"], fetch=feeds.get)
    assert [e["show"] for e in out] == ["Busy"]
    assert tr.call_count == 1


def test_an_unreachable_feed_is_skipped(tmp_path):
    feeds = {"b": feed("Busy", ep("b1"))}
    with patch.object(listening, "transcribe_episode", return_value=(SEGMENTS, 1800)):
        out = make_podcast_entries(tmp_path, client=object(), limit=1, feeds=["down", "b"], fetch=feeds.get)
    assert [e["show"] for e in out] == ["Busy"]


# --- Velora subscriptions → podcasts.txt -------------------------------------

from listening import fetch_velora_subscriptions, sync_podcast_list, render_podcast_list


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSupabase:
    """Records calls; answers sign-in, the progress row, and logout."""

    def __init__(self, podcasts, sign_in_status=200):
        self.podcasts, self.sign_in_status, self.calls = podcasts, sign_in_status, []

    def post(self, url, **kw):
        self.calls.append(("POST", url))
        if "grant_type=password" in url:
            return FakeResponse({"access_token": "tok", "user": {"id": "user-1"}}, self.sign_in_status)
        return FakeResponse({}, 204)

    def get(self, url, params=None, **kw):
        self.calls.append(("GET", url, params))
        return FakeResponse([{"data": {"podcasts": self.podcasts}}])


VELORA_ENV = {
    "VELORA_SUPABASE_URL": "https://proj.supabase.co",
    "VELORA_SUPABASE_ANON_KEY": "anon",
    "VELORA_EMAIL": "me@example.com",
    "VELORA_PASSWORD": "pw",
}


def test_reads_the_followed_shows_and_signs_only_its_own_session_out(monkeypatch):
    for k, v in VELORA_ENV.items():
        monkeypatch.setenv(k, v)
    http = FakeSupabase([
        {"id": "a", "title": "Hidden Brain", "feedUrl": "https://feeds.simplecast.com/kwWc0lhf"},
        {"id": "b", "title": "Broken", "feedUrl": "not a url"},
    ])
    subs = fetch_velora_subscriptions(http)
    assert subs == [{"feedUrl": "https://feeds.simplecast.com/kwWc0lhf", "title": "Hidden Brain"}]
    assert http.calls[1] == ("GET", "https://proj.supabase.co/rest/v1/velora_progress",
                             {"select": "data", "user_id": "eq.user-1"})
    # Signing out every device would log the learner's phone out too.
    assert http.calls[-1] == ("POST", "https://proj.supabase.co/auth/v1/logout?scope=local")


def test_unconfigured_or_failed_sign_in_reads_nothing(monkeypatch):
    for k in VELORA_ENV:
        monkeypatch.delenv(k, raising=False)
    assert fetch_velora_subscriptions(FakeSupabase([])) is None
    for k, v in VELORA_ENV.items():
        monkeypatch.setenv(k, v)
    assert fetch_velora_subscriptions(FakeSupabase([], sign_in_status=400)) is None


def test_podcasts_txt_mirrors_velora_and_round_trips(tmp_path):
    path = tmp_path / "podcasts.txt"
    subs = [{"feedUrl": "https://a.example.com/rss", "title": "Show A"},
            {"feedUrl": "https://b.example.com/rss", "title": ""}]
    feeds, changed = sync_podcast_list(path, fetch=lambda: subs)
    assert feeds == ["https://a.example.com/rss", "https://b.example.com/rss"]
    assert changed is True
    assert read_podcast_list(path) == feeds
    assert sync_podcast_list(path, fetch=lambda: subs)[1] is False  # nothing new to write


def test_falls_back_to_the_file_when_velora_cannot_be_read(tmp_path):
    path = tmp_path / "podcasts.txt"
    path.write_text(render_podcast_list([{"feedUrl": "https://kept.example.com/rss", "title": "Kept"}]), encoding="utf-8")
    assert sync_podcast_list(path, fetch=lambda: None) == (["https://kept.example.com/rss"], False)


def test_unfollowing_everything_in_velora_empties_the_list(tmp_path):
    path = tmp_path / "podcasts.txt"
    path.write_text("https://old.example.com/rss\n", encoding="utf-8")
    assert sync_podcast_list(path, fetch=lambda: []) == ([], True)
    assert read_podcast_list(path) == []


def test_stops_trying_once_gemini_keeps_failing(tmp_path):
    # An overload fails every attempt; burning the whole show list on it
    # would only spend quota.
    feeds = {k: feed(f"Show {k}", ep(f"{k}1")) for k in "abcde"}
    with patch.object(listening, "transcribe_episode", side_effect=RuntimeError("503")) as tr:
        out = make_podcast_entries(tmp_path, client=object(), limit=1, feeds=list("abcde"), fetch=feeds.get)
    assert out == []
    assert tr.call_count == listening.MAX_FAILURES_PER_RUN


def test_a_failed_transcription_skips_only_that_episode(tmp_path):
    calls = iter([RuntimeError("quota"), (SEGMENTS, 1560)])

    def flaky(url, client, listed_duration=0):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r

    with patch.object(listening, "find_podcast_episode", return_value=EPISODE), \
         patch.object(listening, "transcribe_episode", side_effect=flaky):
        out = make_listening_entries(
            [video("AAAAAAAAAA1"), video("AAAAAAAAAA2")], client=object(), repo_path=tmp_path,
        )
    assert [e["id"] for e in out] == ["AAAAAAAAAA2"]
