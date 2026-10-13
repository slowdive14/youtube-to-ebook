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


def test_a_failed_transcription_skips_only_that_episode(tmp_path):
    calls = iter([RuntimeError("quota"), (SEGMENTS, 1560)])

    def flaky(url, client):
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
