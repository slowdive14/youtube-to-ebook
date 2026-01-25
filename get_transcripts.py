"""
Part 2: Extract Transcripts from YouTube Videos
Uses youtube-transcript-api with a robust Selenium fallback.
"""

import sys
import io
import time
import re
import os

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from youtube_transcript_api import YouTubeTranscriptApi


def get_transcript_via_api(video_id):
    """Try to get transcript using the fast API method."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = ' '.join([segment['text'] for segment in transcript_list])
        return full_text.strip()
    except Exception as e:
        return None, str(e)


def get_transcript_via_selenium(video_id):
    """Robust fallback: Scrape transcript by controlling a real browser."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        
        print("  [*] Starting browser for fallback extraction...")
        
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--lang=en-US")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        try:
            # Force hl=en for consistent UI
            url = f"https://www.youtube.com/watch?v={video_id}&hl=en"
            driver.get(url)
            time.sleep(5)
            
            # 1. Expand description
            try:
                expand_btn = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "tp-yt-paper-button#expand, #expand"))
                )
                driver.execute_script("arguments[0].click();", expand_btn)
                time.sleep(2)
            except:
                pass # Already expanded or different layout
            
            # 2. Find and click "Show transcript" button
            # More specific modern YouTube selector first
            transcript_clicked = False
            try:
                transcript_btn = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-description-transcript-section-renderer button"))
                )
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", transcript_btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", transcript_btn)
                transcript_clicked = True
                print("  [*] Clicked transcript button")
                time.sleep(5)
            except:
                # Fallback: look for any element with "transcript" text
                all_els = driver.find_elements(By.XPATH, "//*[contains(text(), 'Transcript') or contains(text(), 'transcript')]")
                for el in all_els:
                    try:
                        if el.is_displayed():
                            driver.execute_script("arguments[0].click();", el)
                            transcript_clicked = True
                            time.sleep(5)
                            break
                    except: continue
            
            # 3. Extract text using the most robust method: Global innerText + logic
            # This handles Shadow DOM and any layout because visible text is always in innerText/textContent
            full_raw_text = driver.execute_script("return document.body.innerText;")
            
            # Clean up the text: try to find the transcript block
            # Transcript portions usually have lots of [0:00] or 0:00 patterns
            timestamps = re.findall(r'\d+:\d+', full_raw_text)
            
            if len(timestamps) > 10:
                # We found something that looks like a transcript!
                # Try to isolate the part between first and last timestamp
                first_ts_idx = full_raw_text.find(timestamps[0])
                last_ts_idx = full_raw_text.rfind(timestamps[-1])
                
                # Take a bit of extra context
                transcript_block = full_raw_text[first_ts_idx:last_ts_idx + 50]
                
                # Basic cleaning: remove timestamps if desired, but for AI summary keeping them is fine
                # and often helps with context. Let's just normalize whitespace.
                clean_text = ' '.join(transcript_block.split())
                return clean_text
            
            return None
                
        finally:
            driver.quit()
            
    except Exception as e:
        print(f"  [!] Selenium error: {str(e)[:80]}")
        return None


def get_transcript(video_id):
    """
    Get the transcript for a YouTube video.
    First tries fast API method, falls back to Selenium if blocked.
    """
    # First attempt: API method (fast)
    result = get_transcript_via_api(video_id)
    
    if isinstance(result, str) and len(result) > 100:
        return result
    
    # API failed or returned very short text (unlikely) - check for blocking
    error_msg = str(result) if not isinstance(result, str) else "Short result"
    
    if "blocking" in error_msg.lower() or "ip" in error_msg.lower() or "429" in error_msg or len(error_msg) < 100:
        print("  [!] API blocked or failed, trying robust browser method...")
        selenium_result = get_transcript_via_selenium(video_id)
        if selenium_result and len(selenium_result) > 100:
            print(f"  [OK] Extraction successful! ({len(selenium_result)} chars)")
            return selenium_result
        else:
            print("  [!] Browser method also failed to find transcript data")
            return None
    
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
            time.sleep(5)

    videos_with_transcripts = [v for v in videos if v.get("transcript")]
    print("=" * 60)
    print(f"Got transcripts for {len(videos_with_transcripts)} of {len(videos)} videos")

    return videos_with_transcripts


if __name__ == "__main__":
    test_video_id = "0J2_YGuNrDo"
    print("Testing robust transcript extraction...")
    transcript = get_transcript(test_video_id)
    if transcript:
        print(f"SUCCESS! First 300 chars:\n{transcript[:300]}...")
