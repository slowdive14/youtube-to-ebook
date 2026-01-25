"""
YouTube Newsletter Generator - Main Script
Ties together all the pieces: fetch videos -> get transcripts -> write articles -> send email
Tracks processed videos to avoid sending duplicates.
Generates both English and Korean versions.
"""

import sys
import io
import argparse
import os
from datetime import datetime
from pathlib import Path

# Fix Windows console encoding for Unicode characters and force flush
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

PROJECT_DIR = Path(__file__).parent
from get_videos import main as fetch_videos, get_video_info_by_id, YOUTUBE_API_KEY
from googleapiclient.discovery import build
from get_transcripts import get_transcripts_for_videos
from write_articles import write_articles_bilingual
from send_email import send_newsletter_bilingual
from video_tracker import filter_new_videos, mark_videos_processed, get_processed_count

LOCK_FILE = PROJECT_DIR / "main.lock"

def run(video_url=None):
    """
    Run the full newsletter pipeline with bilingual support.
    """
    # Prevent concurrent runs which cause duplicate emails
    if LOCK_FILE.exists():
        print(f"\n[!] ALERT: Another instance is already running (found {LOCK_FILE})")
        print("    If you are sure nothing is running, delete this file manually.")
        return

    english_articles, korean_articles = [], []

    try:
        # Create lock file
        with open(LOCK_FILE, "w") as f:
            f.write(str(datetime.now()))
            
        print("\n[DEBUG] Starting run() function...", flush=True)
        if video_url:
            print(f"  Target Video: {video_url}")
        
        print("=" * 60, flush=True)
        print("  YOUTUBE NEWSLETTER GENERATOR (EN + KO)")
        print("=" * 60)
        
        if video_url:
            # Process single video
            print("\n[STEP 1] Fetching single video info...\n")
            video_id = None
            if "v=" in video_url:
                video_id = video_url.split("v=")[1].split("&")[0]
            elif "youtu.be/" in video_url:
                video_id = video_url.split("youtu.be/")[1].split("?")[0]
            
            if not video_id:
                print(f"Invalid video URL: {video_url}")
                return
                
            youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
            video = get_video_info_by_id(youtube, video_id)
            
            if not video:
                print(f"Could not find video info for ID: {video_id}")
                return
                
            new_videos = [video]
        else:
            # Standard channel-based flow
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
            print("No new videos to process.")
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
        # Use detailed mode if processing a specific video URL
        english_articles, korean_articles = write_articles_bilingual(videos_with_transcripts, detailed=(video_url is not None))

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
                v_id = article['url'].split('v=')[-1]  # Extract video_id from URL
                successfully_processed.append({
                    'video_id': v_id,
                    'title': article['title'],
                    'channel': article['channel']
                })
            mark_videos_processed(successfully_processed)
            print(f"\n  [OK] Marked {len(successfully_processed)} video(s) as processed")

        print("\n" + "=" * 60)
        print("  DONE! (English + Korean newsletters sent)")
        print("=" * 60)

    except Exception as e:
        print(f"\n[X] Error during run: {e}")
        raise e
    finally:
        # Always remove the lock file when finished
        if LOCK_FILE.exists():
            try:
                os.remove(LOCK_FILE)
                print("\n  [OK] Process lock released")
            except:
                pass

    return english_articles, korean_articles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Newsletter Generator")
    parser.add_argument("--url", help="Process a specific YouTube video URL")
    args = parser.parse_args()
    
    run(video_url=args.url)
