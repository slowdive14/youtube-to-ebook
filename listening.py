"""
Listening edition for Velora: the day's episodes as podcast audio with a timed
English transcript and its Korean translation.

Why podcast audio rather than the YouTube video: Velora plays it like any
podcast, so it keeps going on a locked phone. YouTube can't do that (background
play is a Premium feature, and its terms forbid separating the audio from the
video). Many channels in the digest are podcasts that also post to YouTube
(NPR, The New York Times, Every), and Apple's directory finds the same episode
by its title — the official audio, from the publisher's own feed.

Why the transcript comes from that audio and not from YouTube's captions: the
podcast file carries ads the video doesn't, so caption times drift a minute or
more by the middle of an episode. Transcribing the file Velora actually plays
keeps every line on the right second. Measured on a 28-minute NPR episode:
segment starts within ~2-3 s of the true time, ads correctly flagged, one
request.

Budget: one Gemini request per ~40 minutes of audio, on LISTENING_MODEL — a
different model from the article pipeline, whose free-tier quota (20/day per
model) is nearly spent by the morning run.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests
from google import genai
from google.genai import types

LISTENING_MODEL = os.getenv("LISTENING_MODEL", "gemini-3-flash-preview")
# Tried when the main model is overloaded (503) or out of quota (429).
LISTENING_FALLBACK_MODEL = os.getenv("LISTENING_FALLBACK_MODEL", "gemini-3.5-flash")
# How many episodes a day get a transcript (each costs 1-2 requests).
LISTENING_PER_DAY = int(os.getenv("LISTENING_PER_DAY", "2"))
# Audio is transcribed in pieces of at most this length: a 40-minute stretch
# is ~25k output tokens (English + Korean), well inside the 65k cap.
CHUNK_SECONDS = 40 * 60
# Episodes kept in the archive (older transcript files are deleted).
KEEP_EPISODES = 60
# A failure tries the next episode, but not indefinitely: when Gemini is
# overloaded every attempt fails (two models each), and attempts during an
# overload appear to count against the daily quota. Stop after this many.
MAX_FAILURES_PER_RUN = 2
# Apple's directory and the video can disagree by a day or two on the date.
DATE_TOLERANCE_DAYS = 4
TITLE_MATCH = 0.85

UA = "VeloraPodcast/1.0 (+https://velora-wine-chi.vercel.app; podcast feed reader)"

PROMPT = """Transcribe this podcast audio for an English learner who will read along while listening.

Return ALL of it, start to finish, as consecutive segments. Each segment:
- start: when the segment begins in THIS audio file, "M:SS" or "H:MM:SS" (absolute time from 0:00 of this file).
- speaker: the speaker's name if known, else "Host" / "Guest".
- en: exactly what is said (verbatim, clean punctuation, drop "um/uh").
- ko: a natural Korean translation of that segment.
- ad: true if the segment is an advertisement, sponsor read or network promo, else false.

Segments are 1-3 sentences (about 8-25 seconds). Start a new segment whenever the speaker changes. Do not skip or summarise anything. JSON only."""

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "start": {"type": "STRING"},
            "speaker": {"type": "STRING"},
            "en": {"type": "STRING"},
            "ko": {"type": "STRING"},
            "ad": {"type": "BOOLEAN"},
        },
        "required": ["start", "en", "ko", "ad"],
    },
}


# ---------------------------------------------------------------------------
# Finding the episode
# ---------------------------------------------------------------------------

def normalize_title(title):
    """Lowercase, unify quotes/dashes, drop punctuation and episode numbers."""
    t = title.lower()
    t = re.sub(r"[‘’“”]", "'", t)
    t = re.sub(r"^(ep(isode)?\.?\s*)?#?\d+\s*[:.\-–—|]\s*", "", t)
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_similarity(a, b):
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def pick_episode(results, title, published=None):
    """
    The directory result that is this video's episode, or None.

    A title match alone isn't enough (shows rerun titles, and generic titles
    collide across shows), so the release date must be close to the video's.
    Without the video's date, the episode must at least be recent.
    """
    when = _parse_date(published)
    tolerance = timedelta(days=DATE_TOLERANCE_DAYS)
    if when is None:
        when = datetime.now(timezone.utc)
        tolerance = timedelta(days=30)
    best, best_score = None, 0.0
    for r in results:
        url = r.get("episodeUrl")
        if not url:
            continue
        score = title_similarity(title, r.get("trackName", ""))
        if score < TITLE_MATCH:
            continue
        released = _parse_date(r.get("releaseDate"))
        if released is None or abs(released - when) > tolerance:
            continue
        if score > best_score:
            best, best_score = r, score
    if not best:
        return None
    return {
        "audioUrl": best["episodeUrl"],
        "show": best.get("collectionName", ""),
        "episodeTitle": best.get("trackName", title),
        "duration": round((best.get("trackTimeMillis") or 0) / 1000),
        "imageUrl": best.get("artworkUrl600") or best.get("artworkUrl160") or "",
        "releaseDate": best.get("releaseDate", ""),
    }


def find_podcast_episode(title, published=None):
    """Look the video's episode up in Apple's podcast directory."""
    url = (
        "https://itunes.apple.com/search?media=podcast&entity=podcastEpisode&limit=8&term="
        + urllib.parse.quote(title[:200])
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return pick_episode(r.json().get("results", []), title, published)
    except Exception as e:
        print(f"  [!] Episode lookup failed for '{title[:50]}': {e}")
        return None


# ---------------------------------------------------------------------------
# Transcribing it
# ---------------------------------------------------------------------------

def clock_to_seconds(value):
    """'1:02:03' / '2:07' / '127' -> seconds, or None."""
    parts = str(value).strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if not 1 <= len(nums) <= 3:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def clean_segments(raw, offset=0.0, limit=None):
    """
    Model output -> ordered segments with start in seconds on the full file's
    clock. Drops rows without text or a readable time, and any time that runs
    backwards or past the chunk (a hallucinated timestamp would otherwise
    break the highlighting for everything after it).
    """
    out = []
    last = -1.0
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        en = str(row.get("en", "")).strip()
        start = clock_to_seconds(row.get("start", ""))
        if not en or start is None:
            continue
        if limit is not None and start > limit + 5:
            continue
        absolute = round(start + offset, 1)
        if absolute < last:
            continue
        last = absolute
        seg = {"start": absolute, "en": en, "ko": str(row.get("ko", "")).strip()}
        speaker = str(row.get("speaker", "")).strip()
        if speaker:
            seg["speaker"] = speaker
        if row.get("ad"):
            seg["ad"] = True
        out.append(seg)
    return out


def _duration(path):
    """Audio length via ffprobe, or None when ffprobe isn't available."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
        )
        return float(out.decode().strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def _chunks(path, duration, workdir):
    """Split long audio into CHUNK_SECONDS pieces (stream copy, no re-encode).
    Without ffmpeg the whole file goes in one request — a very long episode may
    then come back cut short, which is still better than no transcript."""
    if duration <= CHUNK_SECONDS + 5 * 60:
        return [(0.0, Path(path))]
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        print("  [!] ffmpeg not found: transcribing in one piece")
        return [(0.0, Path(path))]
    pieces = []
    start = 0.0
    n = 0
    while start < duration - 5:
        piece = Path(workdir) / f"chunk_{n}.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(CHUNK_SECONDS),
             "-i", str(path), "-c", "copy", str(piece)],
            check=True,
        )
        pieces.append((start, piece))
        start += CHUNK_SECONDS
        n += 1
    return pieces


def _generate(client, uploaded):
    """One transcription call, falling back to a second model on overload or quota."""
    last_error = None
    for model in [LISTENING_MODEL, LISTENING_FALLBACK_MODEL]:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[uploaded, PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SCHEMA,
                    max_output_tokens=65536,
                ),
            )
            return json.loads(resp.text or "[]")
        except Exception as e:  # noqa: BLE001 — any API failure tries the fallback
            last_error = e
            print(f"  [!] {model} failed: {str(e)[:120]}")
    raise RuntimeError(f"transcription failed: {last_error}")


def transcribe_episode(audio_url, client, listed_duration=0):
    """Download the episode and return its timed segments (EN + KO).
    listed_duration (the directory's figure) stands in when ffprobe is missing."""
    with tempfile.TemporaryDirectory() as workdir:
        path = Path(workdir) / "episode.mp3"
        with requests.get(audio_url, headers={"User-Agent": UA}, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for block in r.iter_content(1 << 16):
                    f.write(block)
        duration = _duration(path) or float(listed_duration or 0)
        if duration <= 0:
            duration = float(CHUNK_SECONDS)  # unknown: assume one piece
        segments = []
        for offset, piece in _chunks(path, duration, workdir):
            uploaded = client.files.upload(file=str(piece), config={"mime_type": "audio/mpeg"})
            while uploaded.state and uploaded.state.name == "PROCESSING":
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            try:
                raw = _generate(client, uploaded)
            finally:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass
            segments += clean_segments(raw, offset=offset, limit=min(CHUNK_SECONDS, duration - offset))
        return segments, round(duration)


# ---------------------------------------------------------------------------
# Publishing it
# ---------------------------------------------------------------------------

def video_id(url):
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url or "")
    return m.group(1) if m else ""


def build_entry(video, episode, segments, duration):
    return {
        "id": video_id(video.get("url", "")),
        "title": video.get("title", episode["episodeTitle"]),
        "show": episode["show"],
        "channel": video.get("channel", ""),
        "videoUrl": video.get("url", ""),
        "audioUrl": episode["audioUrl"],
        "imageUrl": episode["imageUrl"],
        "duration": duration or episode["duration"],
        "releaseDate": episode["releaseDate"],
        "addedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "segments": segments,
    }


def listening_dir(repo_path):
    return Path(repo_path) / "src" / "content" / "listening"


def save_entries(entries, repo_path):
    """Write one JSON file per episode; drop the oldest beyond KEEP_EPISODES."""
    folder = listening_dir(repo_path)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for e in entries:
        if not e["id"]:
            continue
        path = folder / f"{e['id']}.json"
        path.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(path)
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in files[KEEP_EPISODES:]:
        old.unlink()
        removed.append(old)
    return written, removed


def already_done(repo_path, vid):
    return (listening_dir(repo_path) / f"{vid}.json").exists()


def make_listening_entries(videos, client=None, repo_path=None, limit=LISTENING_PER_DAY):
    """
    For each video that is a podcast episode, find its audio and transcribe it.
    Videos with no matching episode (YouTube-only channels) are skipped. Any
    failure skips that episode only — the digest itself is never affected.
    """
    client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    entries = []
    failures = 0
    for video in videos:
        if len(entries) >= limit or failures >= MAX_FAILURES_PER_RUN:
            break
        vid = video_id(video.get("url", ""))
        if not vid or (repo_path and already_done(repo_path, vid)):
            continue
        episode = find_podcast_episode(video.get("title", ""), video.get("published"))
        if not episode:
            print(f"  [.] No podcast audio for '{video.get('title', '')[:60]}' (video-only)")
            continue
        print(f"  [.] {episode['show']}: transcribing '{episode['episodeTitle'][:60]}'...")
        try:
            segments, duration = transcribe_episode(episode["audioUrl"], client, episode["duration"])
        except Exception as e:
            failures += 1
            print(f"  [!] Transcription failed (non-fatal): {str(e)[:160]}")
            continue
        if len(segments) < 5:
            print("  [!] Transcript came back nearly empty; skipped")
            continue
        entries.append(build_entry(video, episode, segments, duration))
        print(f"  [OK] {len(segments)} segments over {duration // 60} min")
    return entries


# ---------------------------------------------------------------------------
# Followed podcasts (Step 6): one new episode a day from podcasts.txt
# ---------------------------------------------------------------------------
#
# The shows the learner follows in Velora don't come through YouTube, so the
# digest never sees them. This step reads their feeds directly and gives one
# new episode a day the same transcript, so playing it in Velora shows the
# read-along too.

PODCASTS_FILE = Path(__file__).parent / "podcasts.txt"
PODCASTS_PER_DAY = int(os.getenv("PODCASTS_PER_DAY", "1"))
# Longer episodes are skipped: 75 min is at most two requests (40-min pieces),
# where a 3-hour Huberman episode would be five.
MAX_PODCAST_MINUTES = int(os.getenv("MAX_PODCAST_MINUTES", "75"))
# Only new episodes: a backlog of old ones would starve the newest.
PODCAST_RECENT_DAYS = 14
# Velora's own feed reader, so the audio URL here is exactly the one Velora
# plays — that equality is how Velora attaches the transcript to the episode
# in a followed show's list.
VELORA_API = os.getenv("VELORA_API_BASE", "https://velora-wine-chi.vercel.app").rstrip("/")


def read_podcast_list(path=PODCASTS_FILE):
    """Feed URLs from podcasts.txt, in file order (notes after '#' ignored)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    feeds = []
    for line in lines:
        url = line.split("#", 1)[0].strip()
        if url.startswith("http"):
            feeds.append(url)
    return feeds


def fetch_feed(feed_url):
    """A show's newest episodes, read through Velora's /api/podcast."""
    try:
        r = requests.get(f"{VELORA_API}/api/podcast", params={"feed": feed_url}, timeout=45)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data.get("episodes"), list) else None
    except Exception as e:
        print(f"  [!] Feed unavailable ({feed_url[:50]}): {str(e)[:100]}")
        return None


def podcast_entry_id(episode):
    """Stable, filename-safe id for a feed episode (guids are arbitrary strings)."""
    key = episode.get("id") or episode.get("audioUrl", "")
    return "pod-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def last_done_by_show(repo_path):
    """{show title: newest addedAt} over the episodes already transcribed."""
    out = {}
    folder = listening_dir(repo_path)
    for path in folder.glob("*.json") if folder.exists() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        show, added = data.get("show", ""), data.get("addedAt", "")
        if show and added > out.get(show, ""):
            out[show] = added
    return out


def pick_feed_episode(feed, repo_path, now=None):
    """The newest recent, not-too-long, not-yet-done episode of a show, or None."""
    now = now or datetime.now(timezone.utc)
    for ep in feed.get("episodes", []):  # newest first
        released = _parse_date(ep.get("publishedAt"))
        if released is None or now - released > timedelta(days=PODCAST_RECENT_DAYS):
            continue
        minutes = (ep.get("duration") or 0) / 60
        if minutes > MAX_PODCAST_MINUTES:
            continue
        if not ep.get("audioUrl") or already_done(repo_path, podcast_entry_id(ep)):
            continue
        return ep
    return None


def build_podcast_entry(feed, ep, segments, duration):
    return {
        "id": podcast_entry_id(ep),
        "title": ep.get("title", ""),
        "show": feed.get("title", ""),
        "channel": feed.get("author", ""),
        "videoUrl": "",
        "audioUrl": ep["audioUrl"],
        "imageUrl": ep.get("imageUrl") or feed.get("imageUrl") or "",
        "duration": duration or ep.get("duration") or 0,
        "releaseDate": ep.get("publishedAt", ""),
        "addedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "segments": segments,
    }


def make_podcast_entries(repo_path, client=None, limit=PODCASTS_PER_DAY, feeds=None, fetch=fetch_feed):
    """
    Transcribe up to `limit` new episodes from the followed shows. Shows take
    turns: the one transcribed longest ago (or never) goes first, ties in file
    order — so the list order only decides who starts. A show with nothing new
    simply passes its turn.
    """
    feeds = read_podcast_list() if feeds is None else feeds
    if not feeds or limit <= 0:
        return []
    client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    done = last_done_by_show(repo_path)

    loaded = []
    for url in feeds:
        feed = fetch(url)
        if feed:
            loaded.append(feed)
    order = sorted(range(len(loaded)), key=lambda i: (done.get(loaded[i].get("title", ""), ""), i))

    entries = []
    failures = 0
    for i in order:
        if len(entries) >= limit or failures >= MAX_FAILURES_PER_RUN:
            break
        feed = loaded[i]
        ep = pick_feed_episode(feed, repo_path)
        if not ep:
            continue
        print(f"  [.] {feed.get('title', '')}: transcribing '{ep.get('title', '')[:60]}'...")
        try:
            segments, duration = transcribe_episode(ep["audioUrl"], client, ep.get("duration") or 0)
        except Exception as e:
            failures += 1
            print(f"  [!] Transcription failed (non-fatal): {str(e)[:160]}")
            continue
        if len(segments) < 5:
            print("  [!] Transcript came back nearly empty; skipped")
            continue
        entries.append(build_podcast_entry(feed, ep, segments, duration))
        print(f"  [OK] {len(segments)} segments over {duration // 60} min")
    return entries
