"""
Psychology podcasts as an article source (2 of each day's articles).

The 잔향 newsletter curates English psychology podcasts; its feed list is
copied into psych_podcasts.txt. Most of those shows don't put full episodes on
YouTube (Hidden Brain posts one-minute clips, APA and ABC have no podcast
channel), so they can't come through get_videos.py like the other channels.
Instead each feed is read directly and the chosen episode's audio is
transcribed on this PC with the same faster-whisper setup the listening
edition uses (listening.recognize): no third-party transcript site, and every
show works the same way.

An episode becomes a "video" dict like get_videos.py's, plus:
  audio_url  the enclosure to transcribe
  group      "psych" (select_videos.select_daily_videos gives it a psych slot)
  source     "podcast" (no YouTube video: no clip rows, "listen" not "watch")
and its video_id is listening.podcast_entry_id, so processed_videos.json and
the listening edition (Step 6) name the same episode the same way.

Only one episode per show is offered per run: the newest that is new, recent
and not too long. Episodes published before START_DATE are never offered — the
shows' back catalogues are not imported.
"""

import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import requests

FEEDS_FILE = Path(__file__).parent / "psych_podcasts.txt"

# The day the list was copied from 잔향. Nothing older is ever taken.
START_DATE = datetime(2026, 11, 19, tzinfo=timezone.utc)
# An episode not picked within this many days drops out (it lost to newer ones).
RECENT_DAYS = 14
# Whisper runs ~18x real time on this PC: 3 hours of audio is ~10 minutes.
MAX_MINUTES = int(os.getenv("MAX_PSYCH_MINUTES", "180"))


def read_feeds(path=FEEDS_FILE):
    """[(feed_url, show_name)] in file order."""
    feeds = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return feeds
    for line in lines:
        url, _, name = line.partition("#")
        url, name = url.strip(), name.strip()
        if url.startswith("http"):
            feeds.append((url, name))
    return feeds


def parse_duration(value):
    """itunes:duration ("5344", "1:29:04", "52:10") -> seconds, 0 if unknown."""
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return 0
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return int(seconds)


def _clean(html):
    text = re.sub(r"<[^>]+>", " ", unescape(html or ""))
    return re.sub(r"\s+", " ", text).strip()


def _published(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return datetime(*t[:6], tzinfo=timezone.utc)


def _audio(entry):
    for enc in entry.get("enclosures") or []:
        href = enc.get("href") or enc.get("url")
        if href and (str(enc.get("type", "")).startswith("audio") or href.split("?")[0].endswith((".mp3", ".m4a"))):
            return href
    return None


def episode_video(entry, show):
    """A feed entry as a get_videos-style dict, or None if it has no audio."""
    from listening import podcast_entry_id

    audio = _audio(entry)
    published = _published(entry)
    if not audio or not published:
        return None
    guid = entry.get("id") or entry.get("guid") or audio
    return {
        "title": _clean(entry.get("title", "")),
        "video_id": podcast_entry_id({"id": guid, "audioUrl": audio}),
        "description": _clean(entry.get("summary", ""))[:1500],
        "channel": show,
        "url": entry.get("link") or audio,
        "published": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audio_url": audio,
        "duration": parse_duration(entry.get("itunes_duration")),
        "group": "psych",
        "source": "podcast",
    }


def pick_episode(entries, show, is_processed, now=None):
    """The newest entry worth offering today, as a video dict, or None."""
    now = now or datetime.now(timezone.utc)
    videos = [v for v in (episode_video(e, show) for e in entries) if v]
    videos.sort(key=lambda v: v["published"], reverse=True)
    for v in videos:
        published = datetime.strptime(v["published"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if published < START_DATE or now - published > timedelta(days=RECENT_DAYS):
            continue
        if v["duration"] and v["duration"] > MAX_MINUTES * 60:
            continue
        if is_processed(v["video_id"]):
            continue
        return v
    return None


def fetch_feed(url):
    """The parsed feed, or None. Fetched with requests for its timeout —
    feedparser's own fetch can hang on a stalled server."""
    import feedparser
    from listening import UA

    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001 — one dead feed must not stop the rest
        print(f"  [!] Feed unavailable ({url[:50]}): {str(e)[:80]}")
        return None


def fetch_psych_episodes(path=FEEDS_FILE, fetch=fetch_feed, is_processed=None, now=None):
    """One new episode per show at most, in the list's order."""
    if is_processed is None:
        from video_tracker import is_video_processed as is_processed

    feeds = read_feeds(path)
    print(f"\n  Psychology podcasts ({len(feeds)} shows)...")
    out = []
    for url, name in feeds:
        feed = fetch(url)
        if not feed:
            continue
        show = name or feed.get("feed", {}).get("title", "")
        video = pick_episode(feed.get("entries", []), show, is_processed, now=now)
        if video:
            out.append(video)
            print(f"  [OK] {show}: {video['title'][:60]}")
    print(f"  -> {len(out)} new psychology episode(s)")
    return out


def transcribe(video):
    """(transcript text, [{start, text}] per sentence) from the episode audio,
    or (None, []) when it can't be had."""
    from listening import UA, WHISPER_HINT, recognize, split_sentences, whisper_available

    if not whisper_available():
        print(f"  [!] {WHISPER_HINT}")
        return None, []
    try:
        with tempfile.TemporaryDirectory() as workdir:
            path = Path(workdir) / "episode.mp3"
            with requests.get(video["audio_url"], headers={"User-Agent": UA}, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for block in r.iter_content(1 << 16):
                        f.write(block)
            words, _ = recognize(path)
    except Exception as e:  # noqa: BLE001 — the episode is skipped, never the digest
        print(f"  [!] Audio transcription failed: {str(e)[:120]}")
        return None, []
    sentences = split_sentences(words)
    segments = [{"start": round(s["start"], 1), "text": s["text"]} for s in sentences]
    return " ".join(s["text"] for s in sentences), segments
