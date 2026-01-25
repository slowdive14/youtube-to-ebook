"""
Part 2: Extract Transcripts from YouTube Videos
Uses youtube-transcript-api for reliable transcript extraction.
"""

import sys
import io
import time

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from youtube_transcript_api import YouTubeTranscriptApi


def get_transcript(video_id):
    """
    Get the transcript for a YouTube video.
    Returns the full text of everything said in the video.
    Supports optional cookies to avoid IP blocks.
    """
    try:
        # Look for cookies file to bypass IP blocks (especially on cloud servers)
        cookies_file = os.path.join(os.path.dirname(__file__), "youtube_cookies.txt")
        
        if os.path.exists(cookies_file):
            print(f"  [.] Using cookies from {cookies_file}")
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, cookies=cookies_file)
        else:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

        # Combine all segments into one text
        full_text = ' '.join([segment.text for segment in transcript_list])
        return full_text.strip()

    except Exception as e:
        error_msg = str(e)
        if "blocking" in error_msg.lower() or "ip" in error_msg.lower():
            print(f"  [!] YouTube IP block - try using VPN or wait")
        elif "No transcripts" in error_msg or "disabled" in error_msg.lower():
            print(f"  [!] No captions available for this video")
        else:
            print(f"  [!] Error: {error_msg[:80]}")
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

        # Delay between requests to avoid rate limiting
        if i < len(videos) - 1:
            time.sleep(7)

    # Filter out videos without transcripts
    videos_with_transcripts = [v for v in videos if v.get("transcript")]

    print("=" * 60)
    print(f"Got transcripts for {len(videos_with_transcripts)} of {len(videos)} videos")

    return videos_with_transcripts


# Test it standalone
if __name__ == "__main__":
    test_video_id = "dQw4w9WgXcQ"
    print("Testing transcript extraction...")
    transcript = get_transcript(test_video_id)
    if transcript:
        print(f"Got transcript! First 200 chars:\n{transcript[:200]}...")
