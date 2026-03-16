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
import json
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
MAX_RETRIES = 5
RETRY_DELAY = 30  # seconds to wait on rate limit error (legacy, controlled by backoff now)


def write_article(video, is_first=True, language='en', detailed=False):
    """
    Use Gemini to transform a video transcript into a magazine-style article.
    language: 'en' for English, 'ko' for Korean
    detailed: if True, generates a much longer and more comprehensive article
    """
    # Truncate transcript if too long (to reduce token usage)
    transcript = video['transcript']
    max_words = 8000
    words = transcript.split()
    if len(words) > max_words:
        transcript = ' '.join(words[:max_words]) + "\n\n[Transcript truncated for length...]"

    if language == 'ko':
        style_guide = """매거진 스타일의 기사를 작성하세요.

## 가독성 (최우선)
- 한국어로 자연스럽게 읽히는 문장을 우선하세요
- 복잡한 개념은 쉬운 비유나 예시로 풀어서 설명하세요
- 긴 문장보다 짧고 명확한 문장을 사용하세요
- 문화적 맥락이 다른 표현은 한국 독자에게 친숙한 방식으로 의역하세요

## 원문 내용 보존
- 원문의 핵심 메시지, 주장, 논거는 빠짐없이 전달하세요
- 화자의 의도를 왜곡하지 않되, 표현은 자연스럽게 다듬으세요
- 중요한 인사이트, 데이터, 인용구를 포착하세요

## 전문 용어 처리
- 전문 용어는 한글 번역과 영어를 병기하세요 (예: 강화학습(Reinforcement Learning))
- 널리 쓰이는 약어는 그대로 사용 가능 (예: AI, API, CEO)
- 처음 등장 시 간단한 설명을 덧붙이세요

## 기사 형식
- 매력적인 헤드라인 (비디오 제목과 다르게)
- 도입부에서 핵심을 요약하여 독자의 관심을 끄세요
- 논리적 흐름: 배경 → 핵심 주장 → 근거 → 시사점
- 비디오 요약이 아닌 독립적인 기사로 작성
- 마크다운 형식
- 반드시 한국어로 작성"""

        if detailed:
            style_guide += """

## 심층 분석 모드
- 단순 요약을 넘어 콘텐츠의 핵심 메시지와 맥락을 깊이 있게 유지하세요
- 각 주요 주제에 대해 상세한 설명과 배경 지식을 포함하세요
- 화자가 제시한 데이터, 연구 결과, 구체적 사례를 상세히 서술하세요
- 복잡한 논증도 독자가 따라올 수 있도록 단계별로 쉽게 풀어쓰세요
- 중요한 인용구는 뉘앙스를 살리되 자연스러운 한국어로 옮기세요
- 분량은 표준 요약보다 훨씬 길고 풍부하게 작성하세요"""

        prompt = f"""이 YouTube 비디오 트랜스크립트를 잘 작성된 한국어 기사로 변환하세요.

제목: {video['title']}
채널: {video['channel']}
URL: {video['url']}

트랜스크립트:
{transcript}

---

{style_guide}"""
    else:
        style_guide = """Write a magazine-style article. Guidelines:
- Engaging headline (different from video title)
- Clear, readable prose for general audience
- Capture key insights, quotes, and surprising points
- Write as standalone article, not video summary
- Markdown format"""

        if detailed:
            style_guide += """
- Go beyond simple summarization to maintain the core message and context in depth.
- Provide detailed explanations of key concepts and arguments.
- Include specific examples or anecdotes mentioned in the video.
- Length should be significantly longer and more comprehensive than a standard summary."""

        prompt = f"""Transform this YouTube video transcript into a well-written article.

TITLE: {video['title']}
CHANNEL: {video['channel']}
URL: {video['url']}

TRANSCRIPT:
{transcript}

---

{style_guide}"""

    retry_wait = 5  # Initial backoff in seconds
    
    for attempt in range(MAX_RETRIES):
        try:
            # Standard delay between DIFFERENT articles (polite behavior)
            if (not is_first or attempt > 0) and attempt == 0:
                print(f"  [.] Waiting {REQUEST_DELAY}s between requests...")
                time.sleep(REQUEST_DELAY)

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=8000,
                    temperature=0.7,
                )
            )
            return response.text

        except Exception as e:
            error_str = str(e).lower()
            
            # Check for overload (503), rate limit (429), or internal error (500)
            is_transient = any(msg in error_str for msg in ['503', 'overloaded', '429', 'quota', '500', 'internal server error'])
            
            if is_transient and attempt < MAX_RETRIES - 1:
                print(f"  [!] API Issue detected ({error_str[:60]}...).")
                print(f"      Retrying in {retry_wait}s (Attempt {attempt + 2}/{MAX_RETRIES})...")
                time.sleep(retry_wait)
                retry_wait *= 2  # Exponential backoff
                continue
            else:
                print(f"  [!] Fatal error generating article: {e}")
                return None

    return None


def write_articles_for_videos(videos, language='en', detailed=False):
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

        article = write_article(video, is_first=(i == 0), language=language, detailed=detailed)

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


def write_articles_bilingual(videos, detailed=False):
    """
    Generate both English and Korean articles for all videos.
    Returns tuple of (english_articles, korean_articles)
    """
    # Generate English articles first
    print("\n" + "=" * 60)
    print(f"  PHASE 1: Generating English articles {'(DETAILED)' if detailed else ''}")
    print("=" * 60)
    english_articles = write_articles_for_videos(videos, language='en', detailed=detailed)

    # Generate Korean articles
    print("\n" + "=" * 60)
    print(f"  PHASE 2: Generating Korean articles {'(DETAILED)' if detailed else ''}")
    print("=" * 60)
    korean_articles = write_articles_for_videos(videos, language='ko', detailed=detailed)

    return english_articles, korean_articles


def generate_drill_sentences(en_articles):
    """
    Generate speaking drill data from English articles.
    Extracts key sentences and creates 4-stage drill material:
    1. Repeat after me (original sentence)
    2. Fill in the blank
    3. Korean → English translation
    4. Pattern variation

    Returns a list of drill sentence objects.
    """
    if not en_articles:
        return []

    # Combine all article texts for context
    articles_text = ""
    for i, a in enumerate(en_articles):
        articles_text += f"\n--- Article {i+1}: {a['title']} ---\n"
        articles_text += a['article'] + "\n"

    prompt = f"""You are an English speaking coach for Korean learners at B1 level aiming for B2.

From the articles below, select exactly {len(en_articles) * 5} key sentences (5 per article) that are most useful for speaking practice.

Selection criteria:
- Contains B2-level vocabulary or expressions
- Has reusable sentence patterns (e.g., "is linked to", "suggests that", "plays a role in")
- Not too long (under 20 words preferred, max 25 words)
- Grammatically rich but natural

For each sentence, provide:
1. sentence: The original English sentence (exact quote from article)
2. korean: Natural Korean translation
3. blank: The sentence with ONE key phrase replaced by _____
4. blank_answer: The removed phrase
5. swap_word: A single word in the sentence that can be easily swapped with another word (pick a noun or adjective that's easy to replace)

IMPORTANT: Return ONLY a valid JSON array with no markdown formatting, no code blocks, no extra text.

Example output format:
[
  {{
    "sentence": "Sleep deprivation is linked to cognitive decline.",
    "korean": "수면 부족은 인지 능력 저하와 관련이 있다.",
    "blank": "Sleep deprivation is linked to _____.",
    "blank_answer": "cognitive decline",
    "swap_word": "decline"
  }}
]

ARTICLES:
{articles_text}"""

    retry_wait = 5
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                print(f"  [.] Waiting {retry_wait}s before retry...")
                time.sleep(retry_wait)
            else:
                # Polite delay after previous API calls
                print(f"  [.] Waiting {REQUEST_DELAY}s between requests...")
                time.sleep(REQUEST_DELAY)

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=16000,
                    temperature=0.3,  # Lower temp for structured output
                )
            )

            # Parse JSON response
            text = response.text.strip()
            # Remove markdown code block if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1]  # Remove first line
                text = text.rsplit("```", 1)[0]  # Remove last ```
                text = text.strip()

            drill_data = json.loads(text)

            # Validate structure
            required_keys = {"sentence", "korean", "blank", "blank_answer", "swap_word"}
            validated = []
            for item in drill_data:
                if isinstance(item, dict) and required_keys.issubset(item.keys()):
                    validated.append(item)

            print(f"  [OK] Generated {len(validated)} drill sentences")
            return validated

        except json.JSONDecodeError as e:
            print(f"  [!] JSON parse error: {e}")
            if attempt < MAX_RETRIES - 1:
                retry_wait *= 2
                continue
            return []
        except Exception as e:
            error_str = str(e).lower()
            is_transient = any(msg in error_str for msg in ['503', 'overloaded', '429', 'quota', '500'])
            if is_transient and attempt < MAX_RETRIES - 1:
                print(f"  [!] API Issue ({error_str[:60]}...). Retrying in {retry_wait}s...")
                retry_wait *= 2
                continue
            else:
                print(f"  [!] Failed to generate drill sentences: {e}")
                return []

    return []


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

    print("Testing article generation with gemini-2.5-flash...")
    article = write_article(test_video, is_first=True)
    if article:
        print("\nGenerated article:\n")
        print(article)
