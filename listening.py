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
keeps every line on the right second.

Why the times come from local speech recognition and not from Gemini: Gemini
writes good text but guesses its timestamps. On a 35-minute Huberman episode
its lines ran 3-4 minutes ahead of the audio from the 10-minute mark on, and
it silently dropped sentences. faster-whisper times every word from the audio
itself (checked against clips cut at those times: exact), so it supplies the
sentences and their starts, and Gemini only works on that text: grouping it
into read-along segments, fixing misheard names, translating, flagging ads.

Budget: one Gemini request (text only) per ~40 minutes of audio, on
LISTENING_MODEL — a different model from the article pipeline, whose
free-tier quota (20/day per model) is nearly spent by the morning run.
Recognition runs on this PC's CPU: base.en did 35 minutes in under 2.
"""

import hashlib
import importlib.util
import json
import os
import re
import tempfile
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
# Local speech recognition model (faster-whisper). small.en spells names
# better but is ~3x slower; Gemini fixes the obvious misses either way.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
# The text goes to Gemini in pieces of at most this much audio: 40 minutes is
# ~25k output tokens (English + Korean), well inside the 65k cap.
CHUNK_SECONDS = 40 * 60
# Recognition sometimes runs on without punctuation: a sentence also ends at a
# silence this long, and is cut once it gets this long.
PAUSE_SECONDS = 2.0
MAX_SENTENCE_SECONDS = 30
# Speech that no segment of Gemini's covers is shown on its own (English
# only) once it is at least this many words; shorter misses are fillers.
GAP_WORDS = 8
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

# No line numbers: asked to cite them, the model drifted by 1-3 sentences in
# 30 of 140 segments while its text stayed right, so segments are placed by
# their text instead (align_segments).
PROMPT = """Below is a speech-recognition transcript of the podcast episode "{title}", one sentence per line. An English learner will read it along with the audio.

Split it into consecutive segments of 1-3 sentences (about 8-25 seconds of speech). Never put two speakers in one segment. Keep every line, in order. For each segment:
- speaker: the speaker's name when the conversation makes it clear, else "Host" / "Guest".
- en: the text of its sentences. Fix only clear recognition errors (misheard names or terms, punctuation); never add, drop, reorder or reword anything.
- ko: a natural Korean translation of en.
- ad: true for an advertisement, sponsor read or network promo, else false.
JSON only.

{lines}"""

SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "speaker": {"type": "STRING"},
            "en": {"type": "STRING"},
            "ko": {"type": "STRING"},
            "ad": {"type": "BOOLEAN"},
        },
        "required": ["en", "ko", "ad"],
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

WHISPER_HINT = 'Listening skipped: speech recognition missing (py -m pip install faster-whisper "av<17")'


def whisper_available():
    return importlib.util.find_spec("faster_whisper") is not None


_whisper = None


def recognize(path):
    """[(start, end, text)] for every spoken word, and the audio's length."""
    global _whisper
    from faster_whisper import WhisperModel  # heavy; only loaded to transcribe

    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    # vad_filter skips music and silence, where recognition tends to invent
    # words; not conditioning on the previous text stops repetition loops.
    segments, info = _whisper.transcribe(
        str(path), language="en", word_timestamps=True, vad_filter=True,
        condition_on_previous_text=False, beam_size=1,
    )
    words = [(w.start, w.end, w.word) for seg in segments for w in seg.words or []]
    return words, info.duration


# "Dr." and initials ("U.S.", "J.") end with a period but not a sentence.
ABBREVIATIONS = {"dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "vs.", "jr.", "sr.", "e.g.", "i.e."}


def _ends_sentence(word):
    w = word.strip().rstrip("\"')]”’")
    if not w.endswith((".", "?", "!")):
        return False
    return w.lower() not in ABBREVIATIONS and not re.fullmatch(r"(?:[A-Z]\.)+", w)


def split_sentences(words):
    """
    Recognized words -> sentences [{start, end, text, words}]. A sentence
    ends at . ? !, at a silence of PAUSE_SECONDS, or once it reaches
    MAX_SENTENCE_SECONDS. Each word carries its own leading space.
    """
    sentences, current = [], []

    def close():
        text = "".join(w[2] for w in current).strip()
        if text:
            sentences.append({"start": current[0][0], "end": current[-1][1], "text": text, "words": list(current)})
        current.clear()

    for word in words:
        if current and (
            word[0] - current[-1][1] >= PAUSE_SECONDS
            or word[1] - current[0][0] > MAX_SENTENCE_SECONDS
        ):
            close()
        current.append(word)
        if _ends_sentence(word[2]):
            close()
    if current:
        close()
    return sentences


def sentence_blocks(sentences, span=CHUNK_SECONDS):
    """[(i, j)] index ranges of sentences, each at most `span` seconds of audio."""
    blocks, i = [], 0
    while i < len(sentences):
        j = i + 1
        while j < len(sentences) and sentences[j]["end"] - sentences[i]["start"] <= span:
            j += 1
        blocks.append((i, j))
        i = j
    return blocks


def _words(text):
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def align_segments(words, rows):
    """
    Gemini's segments -> segments timed from the recognized words. Each is
    found in the audio by its text (word-level matching), so the model never
    decides a time: a segment starts at the word its text begins with. Speech
    no segment covers (GAP_WORDS or more) becomes a segment of its own, in
    English only; a segment whose text matches nothing joins the one before.
    """
    tokens = [(t, n) for n, w in enumerate(words) for t in _words(w[2])]
    rows = [r for r in rows if isinstance(r, dict) and str(r.get("en", "")).strip()] if isinstance(rows, list) else []
    if not tokens:
        return []
    said = [_words(str(r["en"])) for r in rows]
    match = {}
    flat = [t for ts in said for t in ts]
    for a, b, size in SequenceMatcher(None, flat, [t for t, _ in tokens], autojunk=False).get_matching_blocks():
        for d in range(size):
            match[a + d] = b + d

    def word_at(i):
        return tokens[i][1] if i < len(tokens) else len(words)

    out = []
    cursor = 0  # first heard token not yet covered

    def add_gap(upto):
        if upto - cursor >= GAP_WORDS:
            for s in split_sentences(words[word_at(cursor):word_at(upto)]):
                out.append({"start": round(s["start"], 1), "en": s["text"], "ko": ""})

    pos = 0
    for r, ts in zip(rows, said):
        hits = [(j - pos, match[j]) for j in range(pos, pos + len(ts)) if j in match]
        pos += len(ts)
        en, ko = str(r["en"]).strip(), str(r.get("ko", "")).strip()
        start = max(cursor, hits[0][1] - hits[0][0]) if hits else None
        if start is None or start >= len(tokens):
            if out:
                out[-1]["en"] += " " + en
                out[-1]["ko"] = f"{out[-1]['ko']} {ko}".strip()
                continue
            start = cursor
        add_gap(start)
        seg = {"start": round(words[word_at(start)][0], 1), "en": en, "ko": ko}
        speaker = str(r.get("speaker", "")).strip()
        if speaker:
            seg["speaker"] = speaker
        if r.get("ad"):
            seg["ad"] = True
        out.append(seg)
        cursor = max(cursor, hits[-1][1] + 1) if hits else cursor
    add_gap(len(tokens))
    return out


def _generate(client, prompt):
    """One Gemini call, falling back to a second model on overload or quota."""
    last_error = None
    for model in [LISTENING_MODEL, LISTENING_FALLBACK_MODEL]:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=[prompt],
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
    raise RuntimeError(f"Gemini failed: {last_error}")


def transcribe_episode(audio_url, client, title=""):
    """Download the episode and return its timed segments (EN + KO) and length.
    title helps Gemini spell the guest's name and the topic's terms."""
    with tempfile.TemporaryDirectory() as workdir:
        path = Path(workdir) / "episode.mp3"
        with requests.get(audio_url, headers={"User-Agent": UA}, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for block in r.iter_content(1 << 16):
                    f.write(block)
        words, duration = recognize(path)
    sentences = split_sentences(words)
    segments = []
    for i, j in sentence_blocks(sentences):
        block = sentences[i:j]
        rows = _generate(client, PROMPT.format(title=title, lines="\n".join(s["text"] for s in block)))
        segments += align_segments([w for s in block for w in s["words"]], rows)
    untranslated = sum(1 for s in segments if not s["ko"])
    if untranslated * 2 > len(segments):
        raise RuntimeError(f"Gemini translated only {len(segments) - untranslated} of {len(segments)} segments")
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


def redo_entries(repo_path, ids=None, client=None):
    """
    Transcribe saved episodes again (same id, audio and details), e.g. after
    the method changed. ids None = every saved episode. Returns the new
    entries; a failure leaves that episode's old file as it was.
    """
    if not whisper_available():
        print(f"  [!] {WHISPER_HINT}")
        return []
    folder = listening_dir(repo_path)
    paths = [folder / f"{i}.json" for i in ids] if ids else sorted(folder.glob("*.json"))
    client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    entries = []
    for path in paths:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            print(f"  [.] {old['show']}: transcribing '{old['title'][:60]}' again...")
            segments, duration = transcribe_episode(
                old["audioUrl"], client, title=f"{old['show']}: {old['title']}"
            )
        except Exception as e:
            print(f"  [!] {path.stem} failed (kept as it was): {str(e)[:160]}")
            continue
        if len(segments) < 5:
            print(f"  [!] {path.stem}: transcript came back nearly empty (kept as it was)")
            continue
        entries.append({**old, "duration": duration or old.get("duration", 0), "segments": segments})
        print(f"  [OK] {len(segments)} segments over {duration // 60} min")
    return entries


def make_listening_entries(videos, client=None, repo_path=None, limit=LISTENING_PER_DAY):
    """
    For each video that is a podcast episode, find its audio and transcribe it.
    Videos with no matching episode (YouTube-only channels) are skipped. Any
    failure skips that episode only — the digest itself is never affected.
    """
    if not whisper_available():
        print(f"  [!] {WHISPER_HINT}")
        return []
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
            segments, duration = transcribe_episode(
                episode["audioUrl"], client, title=f"{episode['show']}: {episode['episodeTitle']}"
            )
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


# --- Velora's subscriptions are the source of truth --------------------------
#
# The learner follows and unfollows shows in Velora; podcasts.txt mirrors that
# list each run (and is the fallback on a day Velora can't be reached). The
# list lives in Velora's Supabase project, one row per account, readable only
# by that account under row level security — so the pipeline signs in as the
# learner, reads just the podcast list, and signs that one session out again.
# Configured in .env: VELORA_SUPABASE_URL, VELORA_SUPABASE_ANON_KEY (Velora's
# public client values), VELORA_EMAIL, VELORA_PASSWORD.


def fetch_velora_subscriptions(http=requests):
    """
    [{feedUrl, title}] in the order they were followed, or None when it can't
    be read (not configured, wrong password, offline). An empty list is a real
    answer: the learner follows nothing.
    """
    url = os.getenv("VELORA_SUPABASE_URL", "").rstrip("/")
    key = os.getenv("VELORA_SUPABASE_ANON_KEY", "")
    email = os.getenv("VELORA_EMAIL", "")
    password = os.getenv("VELORA_PASSWORD", "")
    if not (url and key and email and password):
        return None
    try:
        r = http.post(
            f"{url}/auth/v1/token?grant_type=password",
            headers={"apikey": key},
            json={"email": email, "password": password},
            timeout=20,
        )
        r.raise_for_status()
        token = r.json()
        access, user_id = token["access_token"], token["user"]["id"]
    except Exception as e:
        print(f"  [!] Velora sign-in failed: {str(e)[:120]}")
        return None
    auth = {"apikey": key, "Authorization": f"Bearer {access}"}
    try:
        q = http.get(
            f"{url}/rest/v1/velora_progress",
            params={"select": "data", "user_id": f"eq.{user_id}"},
            headers=auth,
            timeout=20,
        )
        q.raise_for_status()
        rows = q.json()
        podcasts = (rows[0].get("data") or {}).get("podcasts") if rows else []
        return [
            {"feedUrl": p["feedUrl"], "title": p.get("title", "")}
            for p in podcasts or []
            if isinstance(p, dict) and str(p.get("feedUrl", "")).startswith("http")
        ]
    except Exception as e:
        print(f"  [!] Reading Velora subscriptions failed: {str(e)[:120]}")
        return None
    finally:
        # 'local' ends only this session. The default would sign the learner
        # out on every device.
        try:
            http.post(f"{url}/auth/v1/logout?scope=local", headers=auth, timeout=10)
        except Exception:
            pass


PODCASTS_HEADER = """# Podcasts whose new episodes get a read-along transcript for Velora
# (listening.py, Step 6): one episode a day, the shows taking turns.
# MIRRORED FROM VELORA each run: follow or unfollow shows in Velora's podcast
# screen, not here. Edits to this file only matter on a day Velora can't be
# read (then this list is used as is). One RSS feed per line.
"""


def render_podcast_list(subscriptions):
    lines = [PODCASTS_HEADER]
    for s in subscriptions:
        note = f"   # {s['title']}" if s.get("title") else ""
        lines.append(f"{s['feedUrl']}{note}")
    return "\n".join(lines) + "\n"


def sync_podcast_list(path=PODCASTS_FILE, fetch=fetch_velora_subscriptions):
    """
    The feeds to use today, and whether podcasts.txt changed. Velora's list
    when it can be read (podcasts.txt is rewritten to match), otherwise the
    file as it stands.
    """
    subs = fetch()
    if subs is None:
        print("  [.] Velora subscriptions unavailable: using podcasts.txt")
        return read_podcast_list(path), False
    content = render_podcast_list(subs)
    try:
        current = Path(path).read_text(encoding="utf-8")
    except OSError:
        current = ""
    changed = current.replace("\r\n", "\n") != content
    if changed:
        Path(path).write_text(content, encoding="utf-8")
    print(f"  [.] Velora subscriptions: {len(subs)} show(s){' (podcasts.txt updated)' if changed else ''}")
    return [s["feedUrl"] for s in subs], changed


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
    if not whisper_available():
        print(f"  [!] {WHISPER_HINT}")
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
            segments, duration = transcribe_episode(
                ep["audioUrl"], client, title=f"{feed.get('title', '')}: {ep.get('title', '')}"
            )
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


if __name__ == "__main__":
    # Redo saved transcripts with the current method and publish them:
    #   py listening.py --redo              every saved episode
    #   py listening.py --redo <id> <id>    just these (file names without .json)
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if sys.argv[1:2] != ["--redo"]:
        sys.exit("usage: py listening.py --redo [episode id ...]")
    from export_archive import ARCHIVE_REPO_PATH, publish_listening

    if not ARCHIVE_REPO_PATH:
        sys.exit("ARCHIVE_REPO_PATH is not set in .env")
    redone = redo_entries(ARCHIVE_REPO_PATH, ids=sys.argv[2:] or None)
    if redone:
        publish_listening(redone, message=f"Re-time listening transcript(s): {', '.join(e['show'] for e in redone)}")
