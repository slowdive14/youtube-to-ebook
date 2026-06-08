"""
Phase 3: Extract representative frames from a YouTube video + vision-pick.

Pipeline per video:
  1. Download once (yt-dlp, android client, 360p progressive mp4 -> no 403)
  2. For each chosen moment, extract a small candidate window of frames with
     ffmpeg (subtitle timing rarely lines up exactly with the on-screen visual)
  3. Ask Gemini Vision which candidate best matches the caption; keep that one
  4. Fall back to the exact-timestamp frame if vision fails

Pure helpers (frame_filename, build_ffmpeg_cmd, candidate_offsets,
build_vision_prompt, parse_vision_choice, needs_capture) are unit-tested.
The download/ffmpeg/vision orchestration is verified by live smoke test.

Modeled on the KNOU LMS auto-summary capture (Phase 6/6.5) pattern.
"""

import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import re
import json
import subprocess
from pathlib import Path

# Candidate window (seconds) around a chosen moment. Subtitles usually appear
# at or slightly before the visual, so we bias forward.
VISION_OFFSETS = (-2, 0, 3, 6)

# yt-dlp settings proven in Phase 0 recon (android client avoids HTTP 403)
PLAYER_CLIENT = "android"
FORMAT_PREF = "18/best[height<=480]/best"

_UNSAFE = re.compile(r'[^A-Za-z0-9_-]')


def _seconds_to_dashed(seconds):
    """90 -> '01-30', 3725 -> '1-02-05' (MM-SS, or H-MM-SS past an hour)."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}-{m:02d}-{s:02d}" if h else f"{m:02d}-{s:02d}"


def frame_filename(video_id, seconds):
    """Deterministic frame filename, e.g. 'abc123_01-30.jpg'."""
    safe_id = _UNSAFE.sub("_", str(video_id))
    return f"{safe_id}_{_seconds_to_dashed(seconds)}.jpg"


def build_ffmpeg_cmd(src, seconds, out_path):
    """ffmpeg command for a single frame at `seconds` (fast input seek)."""
    return [
        "ffmpeg", "-y",
        "-ss", str(int(seconds)),   # before -i = fast input seek
        "-i", str(src),
        "-frames:v", "1",
        "-q:v", "3",
        str(out_path),
    ]


def candidate_offsets(seconds, duration=None):
    """Candidate second-offsets around a moment, clamped to the video.

    Always includes the exact moment so we never end up with an empty set.
    """
    cands = set()
    for off in VISION_OFFSETS:
        c = int(seconds) + off
        if c < 0:
            continue
        if duration is not None and c > duration:
            continue
        cands.add(c)
    cands.add(max(0, min(int(seconds), duration if duration is not None else int(seconds))))
    return sorted(cands)


def build_vision_prompt(caption, n):
    """Ask the model to pick the best of N candidate frames for a caption."""
    return f"""You are choosing the single best screenshot for a magazine article.

The caption for this image is:
"{caption}"

You are given {n} candidate frames (0-indexed, in order). Choose the ONE that
best matches the caption AND is the clearest, most informative still — prefer
frames showing diagrams, charts, on-screen text, demos, or a meaningful scene.
Reject blurry frames, transitions, black frames, or empty talking-head shots.

Return ONLY JSON: {{"index": <0-based index>, "reason": "<short>"}}.
If NONE of the candidates are usable, return {{"index": -1}}."""


def parse_vision_choice(text, n):
    """Extract a valid 0..n-1 index from the vision response, else None.

    Handles JSON, code fences, and a bare integer. -1 / out-of-range /
    garbage all map to None (caller then uses the exact-timestamp fallback).
    """
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()

    idx = None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            idx = data.get("index")
        elif isinstance(data, int):
            idx = data
    except (json.JSONDecodeError, ValueError):
        # bare integer?
        m = re.search(r'-?\d+', text)
        if m:
            idx = int(m.group())

    if idx is None:
        return None
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return None
    if 0 <= idx < n:
        return idx
    return None


def needs_capture(path):
    """True when the frame is missing or empty (idempotent re-runs)."""
    return (not os.path.exists(path)) or os.path.getsize(path) == 0


# ---------------- Orchestration (live; not unit-tested) ----------------

def _video_id_from_url(url):
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    return url


def download_video(video_url, out_dir):
    """Download a single low-res progressive mp4 via yt-dlp (android client).

    Returns the local file path, or None on failure.
    """
    import yt_dlp

    vid = _video_id_from_url(video_url)
    out_tmpl = str(Path(out_dir) / f"{vid}_src.%(ext)s")
    opts = {
        "format": FORMAT_PREF,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": out_tmpl,
        "overwrites": False,
        "extractor_args": {"youtube": {"player_client": [PLAYER_CLIENT]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
        # resolve actual output path
        base = Path(out_dir) / f"{vid}_src"
        for cand in Path(out_dir).glob(f"{vid}_src.*"):
            return str(cand), info.get("duration")
        return str(base), info.get("duration")
    except Exception as e:
        print(f"  [!] Frame source download failed: {e}")
        return None, None


def _extract_frame(src, seconds, out_path):
    """Run ffmpeg for one frame; return True on a non-empty output."""
    res = subprocess.run(
        build_ffmpeg_cmd(src, seconds, out_path),
        capture_output=True, text=True,
    )
    return res.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _vision_pick(client, caption, candidate_paths):
    """Send candidate frames to Gemini Vision; return chosen index or None."""
    from google.genai import types
    parts = [build_vision_prompt(caption, len(candidate_paths))]
    for p in candidate_paths:
        with open(p, "rb") as f:
            parts.append(types.Part.from_bytes(data=f.read(), mime_type="image/jpeg"))
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=parts,
            config=types.GenerateContentConfig(
                max_output_tokens=200,
                temperature=0.1,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return parse_vision_choice(resp.text or "", len(candidate_paths))
    except Exception as e:
        print(f"  [!] Vision pick failed: {e}")
        return None


def capture_frames_for_moments(video, moments, out_dir, client=None, use_vision=True):
    """Capture one frame per moment. Returns {seconds: jpg_path}.

    Downloads the video once, then for each moment extracts a candidate
    window, vision-picks the best, and keeps a single frame. Frame extraction
    failures are isolated — one bad moment doesn't sink the rest.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cand_dir = out_dir / "_cand"
    cand_dir.mkdir(exist_ok=True)

    video_url = video.get("url", "")
    vid = _video_id_from_url(video_url)

    src, duration = download_video(video_url, str(out_dir))
    if not src:
        return {}
    if duration is None:
        duration = video.get("duration")

    result = {}
    for m in moments:
        seconds = m["seconds"]
        final_path = out_dir / frame_filename(vid, seconds)
        if not needs_capture(str(final_path)):
            result[seconds] = str(final_path)
            continue

        offsets = candidate_offsets(seconds, duration)
        cand_paths = []
        for c in offsets:
            cp = cand_dir / f"{vid}_{c}.jpg"
            if _extract_frame(src, c, str(cp)):
                cand_paths.append((c, str(cp)))

        if not cand_paths:
            print(f"  [!] No frame extracted for moment {seconds}s")
            continue

        chosen_path = None
        if use_vision and client and len(cand_paths) > 1:
            idx = _vision_pick(client, m.get("caption", ""), [p for _, p in cand_paths])
            if idx is not None:
                chosen_path = cand_paths[idx][1]
        if chosen_path is None:
            # fallback: the candidate closest to the exact moment
            chosen_path = min(cand_paths, key=lambda cp: abs(cp[0] - seconds))[1]

        try:
            if os.path.exists(final_path):
                os.remove(final_path)
            os.replace(chosen_path, final_path)
            result[seconds] = str(final_path)
        except OSError as e:
            print(f"  [!] Could not finalize frame {seconds}s: {e}")

    # cleanup: leftover candidates, the (now empty) cand dir, and the source
    # video — frames are kept, but the 16MB+ download shouldn't accumulate.
    for f in cand_dir.glob(f"{vid}_*.jpg"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        cand_dir.rmdir()
    except OSError:
        pass  # non-empty (other videos mid-flight) — leave it
    try:
        os.remove(src)
    except OSError:
        pass

    return result


if __name__ == "__main__":
    # Live smoke: python capture_frames.py VIDEO_ID "MM:SS:caption" ...
    import os as _os
    from dotenv import load_dotenv
    from google import genai
    load_dotenv()

    vid = sys.argv[1] if len(sys.argv) > 1 else "py5HZrVhG_c"
    test_moments = [
        {"seconds": 60, "caption": "The speaker gestures while explaining"},
        {"seconds": 120, "caption": "A key on-screen moment"},
    ]
    cli = genai.Client(api_key=_os.getenv("GEMINI_API_KEY"))
    video = {"url": f"https://www.youtube.com/watch?v={vid}"}
    out = capture_frames_for_moments(video, test_moments, "frames", client=cli)
    print("Captured:", out)
