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
from write_articles import write_articles_bilingual, generate_drill_sentences
# from send_email import send_newsletter_bilingual  # Email disabled
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
        # All runs now use detailed "Deep Analysis" mode
        english_articles, korean_articles = write_articles_bilingual(videos_with_transcripts, detailed=True)

        if not english_articles and not korean_articles:
            print("No articles generated.")
            return

        # Step 3a: Generate Speaking Drill sentences
        print("\n[STEP 3a] Generating Speaking Drill sentences...")
        drill_sentences = []
        if english_articles:
            drill_sentences = generate_drill_sentences(english_articles)
            if drill_sentences:
                print(f"  [OK] {len(drill_sentences)} drill sentences generated")
            else:
                print("  [!] No drill sentences generated (non-fatal)")

        # Step 3b: Generate Audio for Newsletter
        print("\n[STEP 3b] Generating Audio...")

        import shutil
        audio_paths_en = []
        audio_paths_ko = []
        audio_dir = PROJECT_DIR / "audio"
        audio_dir.mkdir(exist_ok=True)

        # Method 1: NotebookLM Podcast (preferred — conversational style)
        nlm_path = shutil.which("nlm") or str(Path(sys.executable).parent / "Scripts" / "nlm.exe")
        if os.path.exists(nlm_path) and english_articles:
            # Re-authenticate NotebookLM before audio generation
            # (tokens may have expired during the long article-generation phase)
            print("  [Auth] Refreshing NotebookLM credentials...")
            try:
                import subprocess as _sp
                _sp.run(
                    [nlm_path, "login"],
                    timeout=60, capture_output=True,
                )
                print("  [Auth] Credentials refreshed.")
            except Exception as _auth_err:
                print(f"  [Auth] Refresh warning (will try anyway): {_auth_err}")

            print("  [Podcast] Trying NotebookLM podcast generation...")
            try:
                from generate_podcast import generate_podcast
                podcast_path = generate_podcast(
                    english_articles, language='en', output_dir=str(audio_dir)
                )
                if podcast_path:
                    audio_paths_en = [podcast_path]
                    print(f"  [Podcast] Success!")
            except Exception as e:
                print(f"  [Podcast] Failed: {e}")

        # Method 2: Azure TTS fallback (plain narration style)
        CHAR_LIMIT = 5000   # ~7min at 0.8x speed, safely under Azure TTS 10-min (600s) timeout

        if not audio_paths_en and os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION"):
            print("  [TTS] Falling back to Azure TTS...")
            from generate_audio import generate_audio

            # Check ffmpeg availability for audio merging
            has_ffmpeg = shutil.which("ffmpeg") is not None
            if not has_ffmpeg:
                print("  [!] WARNING: ffmpeg not found. Multi-chunk audio merge will be unavailable.")
                print("      Install ffmpeg: https://ffmpeg.org/download.html")

            # --- Helper for chunking & merging ---
            def generate_audio_chunks(articles, language, prefix):
                """Generate TTS audio for articles, merging all chunks into a single MP3."""
                if not articles:
                    return []

                # Intro text
                if language == 'ko':
                    current_text = f"유튜브 다이제스트 {datetime.now().strftime('%Y년 %m월 %d일')}.\n\n"
                else:
                    current_text = f"YouTube Digest for {datetime.now().strftime('%B %d, %Y')}.\n\n"

                part_num = 1
                safe_date = datetime.now().strftime('%Y%m%d')
                tmp_paths = []  # Temporary chunk files

                def flush_chunk(text, num):
                    """Generate a single TTS chunk and append to tmp_paths."""
                    tmp_fpath = audio_dir / f"_tmp_{prefix}_part{num}.mp3"
                    print(f"  Generating chunk {num} ({len(text)} chars)...")
                    if generate_audio(text, str(tmp_fpath), language=language):
                        tmp_paths.append(str(tmp_fpath))
                    else:
                        print(f"  [!] WARNING: Failed to generate chunk {num}. Audio may be incomplete.")

                for i, article in enumerate(articles):
                    # Clean text
                    clean_body = article['article'].replace("#", "").replace("*", "").replace("`", "")
                    if language == 'ko':
                        article_text = f"다음 기사: {article['title']}, 채널: {article['channel']}.\n\n{clean_body}\n\n"
                    else:
                        article_text = f"Next Article: {article['title']} from {article['channel']}.\n\n{clean_body}\n\n"

                    # Check limit
                    if len(current_text) + len(article_text) > CHAR_LIMIT:
                        # Flush current text as temporary chunk
                        if current_text.strip():
                            flush_chunk(current_text, part_num)
                            part_num += 1

                        # Start new chunk
                        current_text = article_text
                    else:
                        current_text += article_text

                # Flush remaining
                if current_text.strip():
                    flush_chunk(current_text, part_num)

                if not tmp_paths:
                    return []

                # Final output path (always single file)
                final_path = str(audio_dir / f"Newsletter_{safe_date}_{prefix}.mp3")

                # Remove existing file if re-running on same day
                if os.path.exists(final_path):
                    os.remove(final_path)

                if len(tmp_paths) == 1:
                    # Single chunk — just move, no merge needed
                    shutil.move(tmp_paths[0], final_path)
                    print(f"  Audio saved: {final_path}")
                elif not has_ffmpeg:
                    # ffmpeg unavailable — return separate chunks as fallback
                    print(f"  [!] Skipping merge (ffmpeg not found). Returning {len(tmp_paths)} separate files.")
                    return tmp_paths
                else:
                    # Merge all chunks into single MP3 via ffmpeg concat demuxer
                    import subprocess
                    print(f"  Merging {len(tmp_paths)} chunks into single file...")
                    filelist_path = str(audio_dir / f"_tmp_{prefix}_filelist.txt")
                    try:
                        with open(filelist_path, 'w', encoding='utf-8') as f:
                            for p in tmp_paths:
                                # ffmpeg concat requires forward slashes or escaped backslashes
                                f.write(f"file '{p.replace(os.sep, '/')}'\n")
                        result = subprocess.run(
                            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                             "-i", filelist_path, "-c", "copy", final_path],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0:
                            print(f"  Merged audio saved: {final_path}")
                        else:
                            print(f"  [!] ERROR merging audio: {result.stderr[:200]}")
                            print(f"  Returning {len(tmp_paths)} separate files as fallback.")
                            return tmp_paths
                    except Exception as e:
                        print(f"  [!] ERROR merging audio: {e}. Returning separate files.")
                        return tmp_paths
                    finally:
                        # Always clean up temporary files
                        for p in [filelist_path] + tmp_paths:
                            try:
                                os.remove(p)
                            except OSError:
                                pass

                return [final_path]

            # Generate chunks
            if english_articles:
                print(f"  Processing English Audio ({len(english_articles)} articles)...")
                audio_paths_en = generate_audio_chunks(english_articles, 'en', 'EN')
                
            # Korean audio generation disabled (uncomment to re-enable)
            # if korean_articles:
            #     print(f"  Processing Korean Audio ({len(korean_articles)} articles)...")
            #     audio_paths_ko = generate_audio_chunks(korean_articles, 'ko', 'KO')

        else:
            print("  Skipping Audio: AZURE_SPEECH_KEY or AZURE_SPEECH_REGION not found.")

        # Step 4: Send both newsletters via email (DISABLED)
        # print("\n[STEP 4] Sending newsletters (2 emails)...")
        # success = send_newsletter_bilingual(
        #     english_articles,
        #     korean_articles,
        #     audio_paths_en=audio_paths_en,
        #     audio_paths_ko=audio_paths_ko
        # )
        success = True  # Email disabled — skip to archive export

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

        # Step 4b: Export to archive (if configured)
        if os.getenv("ARCHIVE_REPO_PATH") and success:
            try:
                from export_archive import export_newsletter_issue
                export_newsletter_issue(
                    english_articles, korean_articles,
                    audio_paths_en, audio_paths_ko,
                    drill_sentences=drill_sentences
                )
            except Exception as e:
                print(f"  [!] Archive export failed (non-fatal): {e}")

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
