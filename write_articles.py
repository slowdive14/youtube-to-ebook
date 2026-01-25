"""
Part 3: Transform Transcripts into Magazine Articles using Gemini AI
Takes raw video transcripts and turns them into polished, readable articles.
"""

import sys
import io

# Fix Windows console encoding for Unicode characters
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load your API key
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# Rate limit settings
REQUEST_DELAY = 15  # seconds between requests to avoid rate limits
MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds to wait on rate limit error


def write_article(video, is_first=True, language='en'):
    """
    Use Gemini to transform a video transcript into a magazine-style article.
    language: 'en' for English, 'ko' for Korean
    """
    # Truncate transcript if too long (to reduce token usage)
    transcript = video['transcript']
    max_words = 8000
    words = transcript.split()
    if len(words) > max_words:
        transcript = ' '.join(words[:max_words]) + "\n\n[Transcript truncated for length...]"

    if language == 'ko':
        prompt = f"""이 YouTube 비디오 트랜스크립트를 잘 작성된 한국어 기사로 변환하세요.

제목: {video['title']}
채널: {video['channel']}
URL: {video['url']}

트랜스크립트:
{transcript}

---

매거진 스타일의 기사를 작성하세요. 가이드라인:
- 매력적인 헤드라인 (비디오 제목과 다르게)
- 일반 독자를 위한 명확하고 읽기 쉬운 문장
- 핵심 인사이트, 인용구, 놀라운 포인트 포착
- 비디오 요약이 아닌 독립적인 기사로 작성
- 마크다운 형식
- 반드시 한국어로 작성"""
    else:
        prompt = f"""Transform this YouTube video transcript into a well-written article.

TITLE: {video['title']}
CHANNEL: {video['channel']}
URL: {video['url']}

TRANSCRIPT:
{transcript}

---

Write a magazine-style article. Guidelines:
- Engaging headline (different from video title)
- Clear, readable prose for general audience
- Capture key insights, quotes, and surprising points
- Write as standalone article, not video summary
- Markdown format"""

    for attempt in range(MAX_RETRIES):
        try:
            # Wait before request (skip first if it's the first article)
            if not is_first or attempt > 0:
                print(f"  [.] Waiting {REQUEST_DELAY}s for rate limit...")
                time.sleep(REQUEST_DELAY)

            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=4000,
                    temperature=0.7,
                )
            )
            return response.text

        except Exception as e:
            error_str = str(e)
            if '429' in error_str or 'quota' in error_str.lower():
                if attempt < MAX_RETRIES - 1:
                    print(f"  [!] Rate limited. Waiting {RETRY_DELAY}s before retry {attempt + 2}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY)
                    continue
            print(f"  [!] Error generating article: {e}")
            return None

    return None


def write_articles_for_videos(videos, language='en'):
    """
    Generate articles for all videos with transcripts.
    Rate-limited to avoid API quota issues.
    language: 'en' for English, 'ko' for Korean
    """
    lang_name = "Korean" if language == 'ko' else "English"
    print(f"\nGenerating {lang_name} articles with Gemini AI...")
    print(f"Processing {len(videos)} videos with {REQUEST_DELAY}s delay between requests\n")
    print("=" * 60)

    articles = []

    for i, video in enumerate(videos):
        print(f"\n[{i+1}/{len(videos)}] {video['title'][:50]}...")

        article = write_article(video, is_first=(i == 0), language=language)

        if article:
            articles.append({
                "title": video["title"],
                "channel": video["channel"],
                "url": video["url"],
                "article": article
            })
            print(f"  [OK] Article generated!")
        else:
            print(f"  [X] Failed to generate article")

    print("\n" + "=" * 60)
    print(f"Generated {len(articles)} of {len(videos)} {lang_name} articles")

    return articles


def write_articles_bilingual(videos):
    """
    Generate both English and Korean articles for all videos.
    Returns tuple of (english_articles, korean_articles)
    """
    # Generate English articles first
    print("\n" + "=" * 60)
    print("  PHASE 1: Generating English articles")
    print("=" * 60)
    english_articles = write_articles_for_videos(videos, language='en')

    # Generate Korean articles
    print("\n" + "=" * 60)
    print("  PHASE 2: Generating Korean articles")
    print("=" * 60)
    korean_articles = write_articles_for_videos(videos, language='ko')

    return english_articles, korean_articles


# Test it standalone
if __name__ == "__main__":
    # Test with a mock video
    test_video = {
        "title": "Test Video",
        "channel": "Test Channel",
        "url": "https://youtube.com/watch?v=test",
        "description": "A test video description",
        "transcript": "Hello everyone, today we're going to talk about something really exciting. I've been working on this project for months and I can't wait to share it with you. The main idea is simple but powerful..."
    }

    print("Testing article generation with gemini-3-flash-preview...")
    article = write_article(test_video, is_first=True)
    if article:
        print("\nGenerated article:\n")
        print(article)
