"""
Phase 0 recon: validate yt-dlp + ffmpeg frame extraction for YouTube videos.

Compares two strategies for grabbing a single frame at a given timestamp:
  A) STREAM-SEEK: ask yt-dlp for a direct stream URL, then `ffmpeg -ss` into it.
  B) DOWNLOAD-THEN-SEEK: download a low-res (360p-ish) file once, then seek locally.

Prints timing for both and writes the extracted frames to recon_shots/ so a
human can eyeball them (black screen / 403 / real frame?).

Usage:
    py recon_frame.py [VIDEO_ID_OR_URL] [SECONDS]

Defaults to a known processed video and t=60s.
"""

import sys
import io
import os
import time
import subprocess
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OUT_DIR = Path(__file__).parent / "recon_shots"
OUT_DIR.mkdir(exist_ok=True)

# RECON FINDING (2026-05-27): the default 'web' client resolves DASH/AV1
# video-only URLs that ffmpeg/yt-dlp can't fetch (HTTP 403 Forbidden). The
# 'android' player client instead serves the classic progressive format 18
# (360p combined H.264+AAC MP4) which downloads cleanly. So:
#   - WINNER: download-then-seek with player_client=android, format 18/best<=360
#   - stream-seek into a resolved URL is NOT viable (403)
PLAYER_CLIENT = "android"
FORMAT_PREF = "18/best[height<=480]/best"


def _vid_to_url(vid):
    if vid.startswith("http"):
        return vid
    return f"https://www.youtube.com/watch?v={vid}"


def get_stream_url(url):
    """Use yt-dlp (python module) to resolve a direct media stream URL."""
    import yt_dlp
    opts = {
        "format": FORMAT_PREF,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        # If a single format was chosen, info['url'] holds the direct URL.
        # Otherwise dig into requested_formats.
        if info.get("url"):
            return info["url"], info
        reqs = info.get("requested_formats") or []
        if reqs:
            return reqs[0]["url"], info
        raise RuntimeError("Could not resolve a direct stream URL")


def ffmpeg_grab(src, seconds, out_path):
    """Extract a single frame at `seconds` from `src` (URL or file)."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(seconds),     # -ss BEFORE -i = fast (input) seek
        "-i", src,
        "-frames:v", "1",
        "-q:v", "3",
        str(out_path),
    ]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    ok = res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
    return ok, dt, res.stderr[-400:] if not ok else ""


def download_low_res(url, out_path):
    """Download a single low-res file via yt-dlp (android client = no 403)."""
    import yt_dlp
    opts = {
        "format": FORMAT_PREF,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(out_path),
        "overwrites": True,
        "extractor_args": {"youtube": {"player_client": [PLAYER_CLIENT]}},
    }
    t0 = time.time()
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    dt = time.time() - t0
    # yt-dlp may append an extension; find the actual file
    actual = out_path
    if not actual.exists():
        cands = list(out_path.parent.glob(out_path.stem + ".*"))
        actual = cands[0] if cands else out_path
    return actual, dt


def main():
    vid = sys.argv[1] if len(sys.argv) > 1 else "py5HZrVhG_c"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    url = _vid_to_url(vid)

    print("=" * 60)
    print(f"  RECON: frame capture for {url} @ {seconds}s")
    print("=" * 60)

    # --- Strategy A: stream-seek ---
    print("\n[A] STREAM-SEEK (yt-dlp resolve URL -> ffmpeg -ss into URL)")
    try:
        t0 = time.time()
        stream_url, info = get_stream_url(url)
        resolve_dt = time.time() - t0
        dur = info.get("duration")
        print(f"    Resolved stream URL in {resolve_dt:.1f}s (video duration: {dur}s)")
        print(f"    chosen format: {info.get('format_id') or info.get('format')}")
        out_a = OUT_DIR / f"{vid}_A_streamseek_{seconds}.jpg"
        ok, grab_dt, err = ffmpeg_grab(stream_url, seconds, out_a)
        if ok:
            kb = out_a.stat().st_size // 1024
            print(f"    [OK] frame in {grab_dt:.1f}s -> {out_a.name} ({kb} KB)")
            print(f"    TOTAL A (incl. resolve): {resolve_dt + grab_dt:.1f}s")
        else:
            print(f"    [X] ffmpeg failed in {grab_dt:.1f}s")
            print(f"        {err}")
    except Exception as e:
        print(f"    [X] Strategy A failed: {e}")
        dur = None

    # --- Strategy B: download-then-seek ---
    print("\n[B] DOWNLOAD-THEN-SEEK (yt-dlp download 360p -> local ffmpeg -ss)")
    try:
        dl_path = OUT_DIR / f"{vid}_lowres"
        local_file, dl_dt = download_low_res(url, dl_path)
        kb = local_file.stat().st_size // 1024 if local_file.exists() else 0
        print(f"    Downloaded in {dl_dt:.1f}s -> {local_file.name} ({kb} KB)")
        out_b = OUT_DIR / f"{vid}_B_download_{seconds}.jpg"
        ok, grab_dt, err = ffmpeg_grab(str(local_file), seconds, out_b)
        if ok:
            kb = out_b.stat().st_size // 1024
            print(f"    [OK] frame in {grab_dt:.2f}s -> {out_b.name} ({kb} KB)")
            print(f"    TOTAL B (incl. download): {dl_dt + grab_dt:.1f}s")
            print(f"    NOTE: each extra frame after download only costs ~{grab_dt:.2f}s")
        else:
            print(f"    [X] ffmpeg failed: {err}")
    except Exception as e:
        print(f"    [X] Strategy B failed: {e}")

    print("\n" + "=" * 60)
    print(f"  Frames written to: {OUT_DIR}")
    print("  -> Open them and confirm: real frame? black screen? 403?")
    print("=" * 60)


if __name__ == "__main__":
    main()
