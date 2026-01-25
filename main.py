"""
YouTube Newsletter Generator - Main Script
Ties together all the pieces: fetch videos -> get transcripts -> write articles -> send email
Tracks processed videos to avoid sending duplicates.
Generates both English and Korean versions.
"""

import sys
import io

# Fix Windows console encoding for Unicode characters and force flush
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from get_videos import main as fetch_videos
from get_transcripts import get_transcripts_for_videos
from write_articles import write_articles_bilingual
from send_email import send_newsletter_bilingual
from video_tracker import filter_new_videos, mark_videos_processed, get_processed_count


def run():
    """
    Run the full newsletter pipeline with bilingual support.
    """
    print("\n[DEBUG] Starting run() function...", flush=True)
    print("=" * 60, flush=True)
    print("  YOUTUBE NEWSLETTER GENERATOR (EN + KO)")
    print("=" * 60)
    print(f"  Previously processed: {get_processed_count()} videos")

    # Step 1: Fetch latest videos from your channels
    print("\n[STEP 1] Fetching latest videos...\n")
    videos = fetch_videos()

    if not videos:
        print("No videos found. Check your channel list.")
        return

    # Step 1b: Filter out already-processed videos
    print("\n[STEP 1b] Checking for new videos...\n")
    new_videos = filter_new_videos(videos)

    if not new_videos:
        print("No new videos to process. All videos have been sent before.")
        print("=" * 60)
        return

    print(f"\n  -> {len(new_videos)} new video(s) to process\n")

    # Step 2: Get transcripts for those videos
    print("\n[STEP 2] Extracting transcripts...\n")
    videos_with_transcripts = get_transcripts_for_videos(new_videos)

    if not videos_with_transcripts:
        print("No transcripts available for any videos.")
        return

    # Step 3: Generate articles in both English and Korean
    print("\n[STEP 3] Writing articles (English + Korean)...\n")
    english_articles, korean_articles = write_articles_bilingual(videos_with_transcripts)

    if not english_articles and not korean_articles:
        print("No articles generated.")
        return

    # Step 4: Send both newsletters via email
    print("\n[STEP 4] Sending newsletters (2 emails)...\n")
    success = send_newsletter_bilingual(english_articles, korean_articles)

    # Step 5: Mark videos as processed (only those with successfully generated articles)
    if success:
        # Extract video IDs from successfully generated articles
        successfully_processed = []
        for article in english_articles:  # Use english_articles as the source of truth
            video_id = article['url'].split('v=')[-1]  # Extract video_id from URL
            successfully_processed.append({
                'video_id': video_id,
                'title': article['title'],
                'channel': article['channel']
            })
        mark_videos_processed(successfully_processed)
        print(f"\n  [OK] Marked {len(successfully_processed)} video(s) as processed")

    print("\n" + "=" * 60)
    print("  DONE! (English + Korean newsletters sent)")
    print("=" * 60)

    return english_articles, korean_articles


if __name__ == "__main__":
    run()
