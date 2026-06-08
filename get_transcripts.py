"""
Part 2: Extract Transcripts from YouTube Videos
Uses modern youtube-transcript-api. Selenium dependency removed.
"""

import sys
import io
import time
import os
from youtube_transcript_api import YouTubeTranscriptApi

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def seconds_to_mmss(seconds):
    """Format a second offset as MM:SS (or H:MM:SS past one hour).

    Used to label transcript segments so downstream frame capture can map a
    concept back to a video timestamp.
    """
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        total = 0
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_segments_with_timestamps(segments):
    """Render timestamped transcript segments as ``[MM:SS] text`` lines.

    Blank-text segments are dropped. Missing ``start`` defaults to 0s.
    Returns an empty string for an empty/None list.
    """
    if not segments:
        return ""
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{seconds_to_mmss(seg.get('start', 0))}] {text}")
    return "\n".join(lines)


def get_transcript(video_id):
    """
    Get the transcript for a YouTube video using the modern API (v1.x+).
    Returns ``(full_text, segments)`` where segments is a list of
    ``{"start": float_seconds, "text": str}``. Returns ``(None, [])`` on failure.
    """
    try:
        ytt = YouTubeTranscriptApi()
        # Try English first, fall back to any available language
        try:
            result = ytt.fetch(video_id, languages=['en'])
            lang_note = ""
        except Exception:
            result = ytt.fetch(video_id)
            lang_note = ", any language"

        segments = [
            {"start": float(getattr(s, "start", 0) or 0), "text": s.text}
            for s in result.snippets
        ]
        full_text = ' '.join(s.text for s in result.snippets).strip()
        print(f"  [OK] Fetched transcript via API ({len(result.snippets)} snippets{lang_note})")
        return full_text, segments

    except Exception as e:
        print(f"  [X] API Error: {str(e)[:100]}")
        return None, []

def get_transcripts_for_videos(videos):
    """
    Get transcripts for a list of videos.
    """
    print("\nExtracting transcripts...\n")
    print("=" * 60)

    for i, video in enumerate(videos):
        print(f"Getting transcript: {video['title'][:50]}...")

        transcript, segments = get_transcript(video["video_id"])

        if transcript:
            video["transcript"] = transcript
            video["transcript_segments"] = segments  # [{start, text}, ...] for frame capture
            word_count = len(transcript.split())
            print(f"  [OK] Got {word_count} words, {len(segments)} timed segments\n")
        else:
            video["transcript"] = None
            video["transcript_segments"] = []
            print(f"  [X] No transcript available\n")

        # Delay to be nice
        if i < len(videos) - 1:
            time.sleep(2)  # Reduced delay since API is fast

    videos_with_transcripts = [v for v in videos if v.get("transcript")]
    print("=" * 60)
    print(f"Got transcripts for {len(videos_with_transcripts)} of {len(videos)} videos")

    return videos_with_transcripts

if __name__ == "__main__":
    # Test video ID (qi45Jl46Py8 is a recent one we used)
    test_video_id = "qi45Jl46Py8"
    print(f"Testing modern transcript extraction for video: {test_video_id}")
    transcript, segments = get_transcript(test_video_id)
    if transcript:
        print(f"SUCCESS! First 300 chars:\n{transcript[:300]}...")
        print(f"\n{len(segments)} timed segments. First 3 with timestamps:")
        print(format_segments_with_timestamps(segments[:3]))
    else:
        print("FAILURE: No transcript returned.")
