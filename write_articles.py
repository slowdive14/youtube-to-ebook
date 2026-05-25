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


# ---------- Summary diagnostics helpers (Phase 1) ----------

def _extract_finish_reason(response):
    """Return finish_reason as a normalized uppercase string, '' on failure.

    Handles enum (with .name), int, and string forms across SDK versions.
    """
    try:
        cand = response.candidates[0]
        fr = cand.finish_reason
        if fr is None:
            return ''
        if hasattr(fr, 'name'):
            return str(fr.name).upper()
        return str(fr).upper()
    except (AttributeError, IndexError, TypeError):
        return ''


def _is_truncated_finish(finish_reason: str) -> bool:
    """True when the response was cut by the token cap.

    Gemini reports MAX_TOKENS; some SDK variants emit LENGTH.
    """
    fr = (finish_reason or '').upper()
    # 'STOP' must NOT be classified as truncated even if substring 'STOP' appears
    if 'STOP' in fr or 'FINISH_REASON_STOP' in fr:
        return False
    return 'MAX_TOKENS' in fr or 'LENGTH' in fr


def _log_usage_metadata(response, label='Summary'):
    """Log prompt / output / thinking token counts when available.

    Surfaces the actual thinking-token consumption that silently ate the
    output budget before this fix.
    """
    try:
        um = getattr(response, 'usage_metadata', None)
        if um is None:
            return
        prompt_t = getattr(um, 'prompt_token_count', None)
        candidates_t = getattr(um, 'candidates_token_count', None)
        thoughts_t = (
            getattr(um, 'thoughts_token_count', None)
            or getattr(um, 'thinking_token_count', None)
        )
        parts = []
        if prompt_t is not None:
            parts.append(f"prompt={prompt_t}")
        if candidates_t is not None:
            parts.append(f"output={candidates_t}")
        if thoughts_t is not None:
            parts.append(f"thinking={thoughts_t}")
        if parts:
            print(f"  [.] {label} tokens: {', '.join(parts)}")
    except Exception:
        # Diagnostics must never break the main flow
        pass


_SENTENCE_TERMINATORS = '.!?。!?'


def _trim_to_sentence_boundary(text: str) -> str:
    """Trim trailing partial sentence so a truncated response doesn't end mid-word.

    Searches backward for the last sentence terminator. If the cut would
    leave less than 30% of the original text, returns the original (the
    truncation happened too early to salvage anything meaningful).
    """
    if not text:
        return text
    last_idx = -1
    for i in range(len(text) - 1, -1, -1):
        if text[i] in _SENTENCE_TERMINATORS:
            last_idx = i
            break
    if last_idx == -1:
        return text  # no terminator at all — keep original
    # Keep the trim only if it preserves at least 30% of the content
    if (last_idx + 1) < len(text) * 0.3:
        return text
    return text[:last_idx + 1].rstrip()


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
- 기사 제목은 반드시 단일 H1 (`# 제목`) 으로 시작, 내부 섹션은 H2/H3 만 사용
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
- Start with a single H1 headline (`# Title`); use H2/H3 only for internal sections
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


def generate_summary(video, language='en', is_first=True):
    """
    Generate a rich, concrete per-episode summary so a reader can grasp the
    content in depth without reading the full article. Targets 2-3 paragraphs
    (Korean: 500-800 chars, English: 700-1100 chars) covering topic, claims,
    supporting evidence with specifics, counter-arguments where relevant, and
    practical takeaway.

    language: 'en' or 'ko'
    Returns the summary string, or None on failure.
    """
    transcript = video.get('transcript', '')
    # Use only the first portion of the transcript — summary doesn't need full context
    max_words = 5000
    words = transcript.split()
    if len(words) > max_words:
        transcript = ' '.join(words[:max_words]) + "\n\n[Transcript truncated...]"

    if language == 'ko':
        prompt = f"""이 YouTube 영상을 시청하지 않고도 핵심을 충분히 파악할 수 있도록 풍부하고 구체적인 요약을 작성하세요.

제목: {video['title']}
채널: {video['channel']}

트랜스크립트:
{transcript}

---

요약 작성 규칙:

[분량]
- 한국어 기준 약 500~800자 (공백 포함)
- 2~3개의 단락으로 구성 (단락 사이는 빈 줄로 구분)
- 너무 짧으면 안 됨. 한두 문장으로 끝내지 말 것

[필수 포함 요소]
1) 첫 단락: 영상이 다루는 주제와 화자가 던지는 핵심 질문·문제, 그리고 그에 대한 화자의 결론·주장을 명확히 제시
2) 둘째 단락: 주장을 뒷받침하는 구체적 근거 — 인용된 연구, 데이터, 숫자(있는 그대로 명시), 인명, 실험·사례, 화자의 개인 경험 등을 최소 2~3개 구체적으로 서술
3) 셋째 단락(선택): 반론·한계·뉘앙스, 그리고 시청자가 실제로 적용할 수 있는 시사점 또는 행동 함의

[문체]
- "이 영상은…", "이 비디오에서는…" 같은 상투적 도입부 금지. 바로 본 내용부터 서술
- "흥미로운 관점", "다양한 사례", "여러 가지를 다룬다" 같은 추상적·공허한 표현 금지. 무엇이 어떤 식으로 흥미로운지 그 구체적 내용을 직접 적을 것
- 화자가 사용한 인상적 표현이나 비유는 살리되 자연스러운 한국어로
- 전문 용어는 한글(영어) 병기 (예: 강화학습(Reinforcement Learning))
- 마크다운·헤딩·불릿·번호 매기기 사용 금지. 평문 단락으로만 작성"""
    else:
        prompt = f"""Write a rich, concrete summary of this YouTube video so a reader can deeply understand what it covers without watching it.

TITLE: {video['title']}
CHANNEL: {video['channel']}

TRANSCRIPT:
{transcript}

---

Rules:

[Length]
- Roughly 700-1100 characters of English prose (about 120-180 words)
- 2-3 paragraphs separated by blank lines
- Do NOT stop at one or two sentences

[Required content]
1) First paragraph: the topic and the central question the speaker poses, plus the speaker's main claim or conclusion
2) Second paragraph: at least 2-3 specific pieces of supporting evidence — cited studies, numbers (use the actual figures), names, experiments, anecdotes, or personal stories from the speaker
3) Third paragraph (optional): counter-arguments, caveats, nuance, and a practical takeaway the viewer can actually act on

[Style]
- No filler openings like "This video discusses…" or "In this video…" — open with the actual subject
- Banned vague phrases: "interesting perspective", "various examples", "covers many topics". Name them concretely.
- Preserve memorable phrasings or analogies the speaker uses
- No markdown, no headings, no bullets, no numbered lists — paragraphs only"""

    # Light pacing — summary calls happen between heavier article calls
    if not is_first:
        time.sleep(min(REQUEST_DELAY, 8))

    primary_cap = 4000
    text, finish_reason = _call_summary_api(prompt, primary_cap)

    if text is None:
        return None

    # Defense in depth: retry once with doubled cap if truncated
    if _is_truncated_finish(finish_reason):
        retry_cap = primary_cap * 2
        print(f"  [!] Summary hit cap ({primary_cap} tok); retrying with {retry_cap}...")
        text2, finish_reason2 = _call_summary_api(prompt, retry_cap)
        # Keep the longer of the two — retry may still truncate but usually
        # produces more content
        if text2 and len(text2) >= len(text):
            text = text2
            finish_reason = finish_reason2

    # Last resort: still truncated → trim trailing partial sentence so the
    # archive never shows a mid-word cut to the reader
    if _is_truncated_finish(finish_reason):
        print(f"  [!] Still truncated after retry; trimming to sentence boundary")
        text = _trim_to_sentence_boundary(text)

    # Strip stray markdown headings if the model added them anyway
    summary = "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    ).strip()
    return summary or None


def _call_summary_api(prompt, max_output_tokens):
    """One Gemini summary call with transient-error retry.

    Returns (text, finish_reason) on any non-error outcome — including
    truncation. The caller decides whether to retry for truncation.
    Returns (None, '') only after all transient retries are exhausted.

    CRITICAL: Gemini 2.5 Flash enables "thinking" by default, and thinking
    tokens are counted against max_output_tokens. For a focused extraction
    task that yields silent mid-word truncation, so thinking_budget=0.
    """
    retry_wait = 5
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(retry_wait)

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=max_output_tokens,
                    temperature=0.5,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            )

            _log_usage_metadata(response, label='Summary')
            finish_reason = _extract_finish_reason(response)
            if _is_truncated_finish(finish_reason):
                print(f"  [!] Summary truncated (finish_reason={finish_reason})")

            return ((response.text or "").strip(), finish_reason)

        except Exception as e:
            error_str = str(e).lower()
            is_transient = any(msg in error_str for msg in ['503', 'overloaded', '429', 'quota', '500', 'internal server error'])
            if is_transient and attempt < MAX_RETRIES - 1:
                print(f"  [!] Summary API issue ({error_str[:60]}...). Retrying in {retry_wait}s...")
                retry_wait *= 2
                continue
            print(f"  [!] Failed to generate summary: {e}")
            return (None, '')

    return (None, '')


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
            # Per-episode summary so readers can grasp content without reading full article
            print(f"  [.] Generating episode summary...")
            summary = generate_summary(video, language=language, is_first=False)
            if summary:
                print(f"  [OK] Summary ready ({len(summary)} chars)")
            else:
                print(f"  [!] Summary unavailable (non-fatal)")

            articles.append({
                "title": video["title"],
                "channel": video["channel"],
                "url": video["url"],
                "article": article,
                "summary": summary or ""
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


def _salvage_truncated_json(text):
    """
    Attempt to recover complete items from a truncated JSON array.
    1. Fix raw newlines inside string values
    2. If still broken, find the last complete object and close the array
    """
    import re
    # Step 1: Fix newlines inside string values
    repaired = re.sub(
        r'"([^"\\]*(?:\\.[^"\\]*)*)"',
        lambda m: '"' + m.group(1).replace('\n', ' ').replace('\r', '') + '"',
        text
    )
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Step 2: Find last complete object and close the array
    last_complete = repaired.rfind('},')
    if last_complete == -1:
        last_complete = repaired.rfind('}')
    if last_complete != -1:
        truncated = repaired[:last_complete + 1] + ']'
        bracket_pos = truncated.find('[')
        if bracket_pos != -1:
            truncated = truncated[bracket_pos:]
        return json.loads(truncated)

    raise json.JSONDecodeError("Cannot salvage truncated JSON", text, 0)


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

    # Combine all article texts for context (limit to 6000 chars to avoid output truncation)
    articles_text = ""
    for i, a in enumerate(en_articles):
        articles_text += f"\n--- Article {i+1}: {a['title']} ---\n"
        articles_text += a['article'] + "\n"
    if len(articles_text) > 6000:
        articles_text = articles_text[:6000] + "\n...(truncated)"

    num_sentences = min(len(en_articles) * 5, 15)

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

            # Reduce sentence count on later retries to avoid truncation
            if attempt >= 1:
                effective_count = max(num_sentences // 2, 5)
                print(f"  [!] Reducing to {effective_count} sentences for retry")
            else:
                effective_count = num_sentences

            prompt = f"""You are an English speaking coach for Korean learners at B1 level aiming for B2.

From the articles below, select exactly {effective_count} key sentences that are most useful for speaking practice.

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

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=8192,
                    temperature=0.3,  # Lower temp for structured output
                )
            )

            # Check if output was truncated
            if response.candidates and response.candidates[0].finish_reason:
                finish_reason = str(response.candidates[0].finish_reason)
                if "STOP" not in finish_reason:
                    print(f"  [!] Response truncated (finish_reason={finish_reason}), will attempt salvage")

            # Parse JSON response
            text = response.text.strip()
            # Remove markdown code block if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1]  # Remove first line
                text = text.rsplit("```", 1)[0]  # Remove last ```
                text = text.strip()

            try:
                drill_data = json.loads(text)
            except json.JSONDecodeError:
                print(f"  [!] Direct JSON parse failed, attempting salvage (text length: {len(text)} chars)...")
                drill_data = _salvage_truncated_json(text)
                print(f"  [OK] Salvaged {len(drill_data)} items from truncated response")

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
