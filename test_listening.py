"""
Tests for the listening edition (listening.py): matching a video to its
podcast episode, timing the transcript from speech recognition, and
publishing. Network, recognition and Gemini are never touched — they are
patched.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import listening
from listening import (
    normalize_title,
    title_similarity,
    pick_episode,
    split_sentences,
    sentence_blocks,
    align_segments,
    transcribe_episode,
    save_entries,
    make_listening_entries,
)


@pytest.fixture(autouse=True)
def recognizer_installed(monkeypatch):
    monkeypatch.setattr(listening, "whisper_available", lambda: True)


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


# --- timing the transcript ----------------------------------------------------

def words(text, start=0.0, step=0.5):
    """Recognizer-style words: one every `step` seconds, each with its leading space."""
    return [(start + i * step, start + i * step + 0.4, " " + w) for i, w in enumerate(text.split())]


def test_sentences_end_at_punctuation_but_not_after_titles_or_initials():
    out = split_sentences(words("Dr. Epel lives in the U.S. now. Welcome! Is it? Yes."))
    assert [s["text"] for s in out] == ["Dr. Epel lives in the U.S. now.", "Welcome!", "Is it?", "Yes."]
    assert out[1]["start"] == 3.5  # its own first word's time, from the audio


def test_a_long_silence_or_a_run_on_also_ends_a_sentence():
    out = split_sentences(words("so we kept going") + words("and then", start=10))
    assert [s["text"] for s in out] == ["so we kept going", "and then"]
    run_on = split_sentences(words(" ".join(["word"] * 100), step=1.0))
    assert all(s["end"] - s["start"] <= listening.MAX_SENTENCE_SECONDS for s in run_on)
    assert sum(len(s["text"].split()) for s in run_on) == 100  # nothing lost


def sentences(*texts, gap=10.0):
    return [{"start": i * gap, "end": i * gap + 8, "text": t} for i, t in enumerate(texts)]


def test_blocks_split_the_text_by_audio_length():
    s = sentences(*[f"line {i}" for i in range(10)], gap=600)  # one every 10 minutes
    assert sentence_blocks(s, span=40 * 60) == [(0, 4), (4, 8), (8, 10)]
    assert sentence_blocks([], span=60) == []


def test_segments_start_where_their_text_is_heard():
    heard = words("Hey, Lulu here. This show is sponsored. What is a question? Good one.")
    rows = [
        {"en": "Hey, Lulu here. This show is sponsored.", "ko": "룰루입니다. 광고입니다.", "ad": True, "speaker": "Host"},
        {"en": "What is a question? Good one.", "ko": "질문이 뭔가요? 좋네요.", "ad": False},
    ]
    assert align_segments(heard, rows) == [
        {"start": 0.0, "en": "Hey, Lulu here. This show is sponsored.", "ko": "룰루입니다. 광고입니다.",
         "speaker": "Host", "ad": True},
        {"start": 3.5, "en": "What is a question? Good one.", "ko": "질문이 뭔가요? 좋네요."},
    ]


def test_a_fixed_word_neither_moves_the_line_nor_is_undone():
    heard = words("Doctor Epple, welcome. So Martin Bacart measured it.")
    rows = [{"en": "Dr. Epel, welcome.", "ko": "에펠 박사님"}, {"en": "So Martin Picard measured it.", "ko": "마틴 피카드"}]
    out = align_segments(heard, rows)
    assert [(s["start"], s["en"]) for s in out] == [(0.0, "Dr. Epel, welcome."), (1.5, "So Martin Picard measured it.")]


def test_speech_the_model_left_out_still_shows_on_time():
    heard = words("One two three. This sentence was left out by the model entirely. Four five six.")
    rows = [{"en": "One two three.", "ko": "하나"}, {"en": "Four five six.", "ko": "넷"}]
    assert [(s["start"], s["en"], s["ko"]) for s in align_segments(heard, rows)] == [
        (0.0, "One two three.", "하나"),
        (1.5, "This sentence was left out by the model entirely.", ""),
        (6.0, "Four five six.", "넷"),
    ]
    # A dropped "Yeah, right." is a filler, not a missing line.
    short = words("One two three. Yeah, right. Four five six.")
    assert len(align_segments(short, rows)) == 2


def test_text_that_matches_nothing_joins_the_line_before():
    heard = words("One two three. Four five six.")
    rows = [
        {"en": "One two three.", "ko": "하나"},
        {"en": "Completely invented words here.", "ko": "지어냄"},
        "junk",
        {"en": "", "ko": "빈 줄"},
        {"en": "Four five six.", "ko": "넷"},
    ]
    assert [(s["start"], s["en"], s["ko"]) for s in align_segments(heard, rows)] == [
        (0.0, "One two three. Completely invented words here.", "하나 지어냄"),
        (1.5, "Four five six.", "넷"),
    ]


class FakeGemini:
    """Answers every request with each transcript line as its own segment."""

    def __init__(self, translate=True):
        self.prompts, self.translate = [], translate
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, model, contents, config):
        prompt = contents[0]
        self.prompts.append(prompt)
        lines = prompt.split("JSON only.\n\n", 1)[1].split("\n")
        rows = [{"en": line, "ko": f"번역: {line}", "ad": False} for line in lines] if self.translate else []
        return SimpleNamespace(text=json.dumps(rows))


class FakeDownload:
    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        return [b"mp3"]


def test_transcribes_with_recognized_times_and_one_request_per_block(monkeypatch):
    heard = words("First line. Second line.") + words("Third line much later.", start=50 * 60)
    monkeypatch.setattr(listening, "recognize", lambda path: (heard, 3100.4))
    monkeypatch.setattr(listening.requests, "get", FakeDownload)
    gemini = FakeGemini()

    segments, duration = transcribe_episode("https://cdn.example.com/a.mp3", gemini, title="Show: Episode")

    assert duration == 3100
    assert [(s["start"], s["en"], s["ko"]) for s in segments] == [
        (0.0, "First line.", "번역: First line."),
        (1.0, "Second line.", "번역: Second line."),
        (3000.0, "Third line much later.", "번역: Third line much later."),
    ]
    assert len(gemini.prompts) == 2  # 50 minutes apart: two 40-minute blocks
    assert '"Show: Episode"' in gemini.prompts[0]


def test_a_mostly_untranslated_transcript_counts_as_a_failure(monkeypatch):
    heard = words("One two three four five six seven eight. " * 3)
    monkeypatch.setattr(listening, "recognize", lambda path: (heard, 30))
    monkeypatch.setattr(listening.requests, "get", FakeDownload)
    with pytest.raises(RuntimeError, match="translated only 0 of 3"):
        transcribe_episode("https://cdn.example.com/a.mp3", FakeGemini(translate=False))


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

    def flaky(url, client, title=""):
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


def test_redo_keeps_each_episode_and_replaces_only_its_transcript(tmp_path):
    folder = tmp_path / "src" / "content" / "listening"
    folder.mkdir(parents=True)
    old = {"id": "pod-1", "title": "Stress", "show": "Huberman Lab", "audioUrl": "https://cdn.example.com/1.mp3",
           "duration": 2000, "addedAt": "2026-10-14", "segments": [{"start": 0, "en": "old", "ko": "옛"}]}
    (folder / "pod-1.json").write_text(json.dumps(old), encoding="utf-8")
    (folder / "pod-2.json").write_text(json.dumps({**old, "id": "pod-2"}), encoding="utf-8")
    results = iter([(SEGMENTS, 2082), RuntimeError("503")])

    def transcribe(url, client, title=""):
        assert title == "Huberman Lab: Stress"
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    with patch.object(listening, "transcribe_episode", side_effect=transcribe):
        out = listening.redo_entries(tmp_path, client=object())

    assert out == [{**old, "duration": 2082, "segments": SEGMENTS}]
    # The failed one isn't returned, so its file stays as it was.
    assert json.loads((folder / "pod-2.json").read_text(encoding="utf-8"))["segments"][0]["en"] == "old"
