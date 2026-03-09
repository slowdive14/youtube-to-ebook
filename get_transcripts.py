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

def get_transcript(video_id):
    """
    Get the transcript for a YouTube video using the modern API (v1.x+).
    Returns the concatenated transcript text or None if it fails.
    """
    try:
        ytt = YouTubeTranscriptApi()
        # Try English first
        try:
            result = ytt.fetch(video_id, languages=['en'])
            full_text = ' '.join([snippet.text for snippet in result.snippets])
            print(f"  [OK] Fetched English transcript via API ({len(result.snippets)} snippets)")
            return full_text.strip()
        except Exception as e:
            # Fallback: try any available language
            result = ytt.fetch(video_id)
            full_text = ' '.join([snippet.text for snippet in result.snippets])
            print(f"  [OK] Fetched transcript via API ({len(result.snippets)} snippets, any language)")
            return full_text.strip()
            
    except Exception as e:
        print(f"  [X] API Error: {str(e)[:100]}")
        return None

def get_transcripts_for_videos(videos):
    """
    Get transcripts for a list of videos.
    """
    print("\nExtracting transcripts...\n")
    print("=" * 60)

    for i, video in enumerate(videos):
        print(f"Getting transcript: {video['title'][:50]}...")

        transcript = get_transcript(video["video_id"])

        if transcript:
            video["transcript"] = transcript
            word_count = len(transcript.split())
            print(f"  [OK] Got {word_count} words\n")
        else:
            video["transcript"] = None
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
    transcript = get_transcript(test_video_id)
    if transcript:
        print(f"SUCCESS! First 300 chars:\n{transcript[:300]}...")
    else:
        print("FAILURE: No transcript returned.")
