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
import re
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
            _log_usage_metadata(response, label='Article')
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
- 한국어 기준 약 300~500자 (공백 포함)
- 정확히 2개의 단락으로 구성 (단락 사이는 빈 줄 하나로 구분)
- 한 두 문장으로 끝내지 말 것. 그러나 셋째 단락은 절대 만들지 말 것

[필수 포함 요소 — 두 단락 안에 모두 담을 것]
1) 첫 단락: 영상이 다루는 주제와 화자의 핵심 주장·결론을 명확히 제시하고,
   그 주장을 뒷받침하는 가장 구체적인 근거 1~2개(연구·숫자·인명·사례 중 가장 강한 것)를 함께 녹여 넣을 것
2) 둘째 단락: 시청자가 실제로 적용할 수 있는 시사점·행동 함의를 중심으로,
   필요하다면 반론·한계·뉘앙스를 짧게 곁들일 것

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
- Roughly 400-700 characters of English prose (about 70-120 words)
- EXACTLY 2 paragraphs separated by a single blank line — never 3
- Do NOT stop at one or two sentences, but do NOT pad either

[Required content — fit it ALL into two paragraphs]
1) First paragraph: the topic and the speaker's central claim/conclusion,
   plus the 1-2 strongest pieces of supporting evidence (a cited study,
   a specific number, a named experiment, or a concrete anecdote) woven in.
2) Second paragraph: the practical takeaway the viewer can act on, with
   a brief mention of caveat/nuance/counter-argument if relevant.

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


# ---------- Per-section summaries (collapsible reading on the archive site) ----------

_SEC_FENCE_RE = re.compile(r'(```[\s\S]*?```)')
_SEC_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*$', re.MULTILINE)

# Headings that must never get a summary line: language dividers and the
# episode summary (which is itself the article-level summary).
_SEC_SKIP_HEADINGS = {'english', '한국어', 'episode summary', '에피소드 요약'}

SECTION_SUMMARY_MARKER = '[[SUM]]'


def _norm_heading(text):
    """Lowercased, punctuation-light heading key for matching model output."""
    t = re.sub(r'[*_`]', '', text or '').strip()
    t = re.sub(r'\s+', ' ', t)
    return t.lower().rstrip(':.').strip()


def extract_section_headings(article_md):
    """Return the article's section heading texts, in document order.

    Skips fenced code blocks, the language/summary headings the archive site
    keeps permanently expanded, and the article's own title — which becomes
    the H1 and is never collapsed, so a summary line under it would render as
    a stray marker.

    The title is identified as the first heading *after* the skip-list rather
    than by level, because this runs both on raw Gemini output (where the
    title may still be an H2) and on exported issue segments (where the title
    is preceded by a "## English" / "## 한국어" divider).
    """
    if not article_md:
        return []
    plain = ''.join(
        part for i, part in enumerate(_SEC_FENCE_RE.split(article_md)) if i % 2 == 0
    )
    headings = [
        h for m in _SEC_HEADING_RE.finditer(plain)
        for h in [m.group(2).strip()]
        if _norm_heading(h) not in _SEC_SKIP_HEADINGS
    ]
    return headings[1:]  # headings[0] is the article title


def generate_section_summaries(article_md, language='en', is_first=True):
    """Summarize every section of a finished article in one Gemini call.

    Returns {heading_text: summary} — the map the archive site turns into a
    click-to-expand line under each heading. Empty dict on any failure, which
    simply means the site falls back to the section's opening sentence.

    The contract that matters: reading the summaries top-to-bottom must convey
    the whole article, so each one carries the section's actual substance
    rather than describing what the section is "about".
    """
    headings = extract_section_headings(article_md)
    if not headings:
        return {}

    heading_list = "\n".join(f"- {h}" for h in headings)

    if language == 'ko':
        prompt = f"""아래 기사의 각 섹션을 한 줄 요약하세요.

[기사]
{article_md}

[요약할 섹션 제목 — 이 목록에 있는 것만, 제목은 글자 그대로 복사]
{heading_list}

---

가장 중요한 규칙: 독자가 **요약문만 순서대로 읽어도 기사 전체 내용을 명확히 파악**할 수 있어야 합니다.
그러려면 각 요약은 그 섹션이 "무엇에 관한 것인지" 설명하는 게 아니라, 그 섹션이 **실제로 말하는 결론·주장·수치**를 담아야 합니다.

나쁜 예: "이 섹션에서는 장내 미생물에 대해 설명한다." (아무 정보가 없음)
좋은 예: "장에는 수조 개의 미생물이 '작은 약국'처럼 화학물질을 만들며, 건강한 장은 나쁜 균이 없는 상태가 아니라 다양성이 높은 상태다."

규칙:
- 각 요약은 1~2문장, 공백 포함 100자 이내
- "이 섹션은…", "저자는…" 같은 도입부 금지. 내용부터 바로 서술
- 구체적인 숫자·인명·용어는 반드시 살릴 것
- 앞 요약과 자연스럽게 이어지도록 (전체가 하나의 압축된 기사처럼)
- 반드시 한국어

JSON 으로만 답하세요:
{{"summaries": [{{"heading": "<섹션 제목 그대로>", "summary": "<요약>"}}]}}"""
    else:
        prompt = f"""Summarize each section of the article below in one line.

[ARTICLE]
{article_md}

[SECTIONS TO SUMMARIZE — only these, copy each heading verbatim]
{heading_list}

---

The rule that matters most: a reader who reads **only your summaries, in order,
must clearly grasp the entire article**. So each summary must carry what the
section actually *says* — its claim, number, name, or conclusion — not a
description of what the section is "about".

BAD:  "This section discusses the gut microbiome." (conveys nothing)
GOOD: "The gut hosts trillions of microbes acting as 'mini pharmacies'; a healthy
gut is defined by diversity, not by the absence of bad bugs."

Rules:
- 1-2 sentences, 35 words max
- No "This section...", "The author explains..." — state the content directly
- Keep the specific numbers, names, and terms
- Make each summary flow from the previous one, so the set reads as one compressed article
- Same language as the article

Reply with JSON only:
{{"summaries": [{{"heading": "<heading verbatim>", "summary": "<summary>"}}]}}"""

    if not is_first:
        time.sleep(min(REQUEST_DELAY, 8))

    retry_wait = 5
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(retry_wait)

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=3000,
                    temperature=0.4,
                    response_mime_type='application/json',
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            )
            _log_usage_metadata(response, label='Section-summaries')
            return parse_section_summaries(response.text or "", headings)

        except Exception as e:
            error_str = str(e).lower()
            is_transient = any(msg in error_str for msg in ['503', 'overloaded', '429', 'quota', '500', 'internal server error'])
            if is_transient and attempt < MAX_RETRIES - 1:
                print(f"  [!] Section-summary API issue ({error_str[:60]}...). Retrying in {retry_wait}s...")
                retry_wait *= 2
                continue
            print(f"  [!] Failed to generate section summaries: {e}")
            return {}

    return {}


def parse_section_summaries(text, headings):
    """Parse the model's JSON into {original_heading: summary}.

    Matches on a normalized heading key so the model reformatting a heading
    (case, trailing colon, stray emphasis) doesn't drop the summary.
    """
    if not text or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        salvaged = _salvage_truncated_json(text)
        if not isinstance(salvaged, (dict, list)):
            return {}
        data = salvaged

    items = data.get('summaries') if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}

    by_key = {_norm_heading(h): h for h in headings}
    out = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        original = by_key.get(_norm_heading(item.get('heading', '')))
        summary = (item.get('summary') or '').strip()
        if original and summary:
            out[original] = summary
    return out


def inject_section_summaries(article_md, summaries):
    """Insert ``[[SUM]] <summary>`` right after each matching heading.

    Kept out of the canonical ``article['article']`` text — email and audio
    read that, and must never see markers. ``export_archive`` calls this when
    it renders the archive copy.
    """
    if not article_md or not summaries:
        return article_md

    by_key = {_norm_heading(h): s for h, s in summaries.items()}
    out = []
    in_fence = False
    for line in article_md.split('\n'):
        out.append(line)
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _SEC_HEADING_RE.match(line)
        if not m:
            continue
        summary = by_key.get(_norm_heading(m.group(2)))
        if summary:
            out.append('')
            out.append(f'{SECTION_SUMMARY_MARKER} {summary}')
    return '\n'.join(out)


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

            # Per-section summaries so the archive site can show a skimmable
            # summary line per section and hide the full text behind a click
            print(f"  [.] Generating section summaries...")
            section_summaries = generate_section_summaries(
                article, language=language, is_first=False
            )
            if section_summaries:
                print(f"  [OK] {len(section_summaries)} section summaries ready")
            else:
                print(f"  [!] Section summaries unavailable (non-fatal)")

            articles.append({
                "title": video["title"],
                "channel": video["channel"],
                "url": video["url"],
                "article": article,
                "summary": summary or "",
                "section_summaries": section_summaries,
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


# ---------- Frame-moment selection (Phase 2 of video-frame-capture) ----------


def _mmss_to_seconds(ts):
    """Parse 'MM:SS' / 'H:MM:SS' / plain integer string into seconds.

    Returns None if unparseable.
    """
    if ts is None:
        return None
    ts = str(ts).strip()
    if not ts:
        return None
    if ts.isdigit():
        return int(ts)
    parts = ts.split(":")
    if not all(p.strip().isdigit() for p in parts) or len(parts) > 3:
        return None
    parts = [int(p) for p in parts]
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def _seconds_to_mmss(seconds):
    """Local MM:SS formatter (mirror of get_transcripts.seconds_to_mmss).

    Kept local to avoid importing get_transcripts (which pulls in the
    youtube_transcript_api dependency) just for formatting.
    """
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def build_frame_prompt(article, transcript_with_timestamps, n=4):
    """Prompt Gemini to pick the N most visually valuable moments.

    The model sees the article (what matters) plus the timestamped
    transcript (where things happen) and returns timestamps + captions +
    an anchor phrase locating each in the article.
    """
    return f"""You are a photo editor choosing screenshots for a magazine article built from a YouTube video.

Pick EXACTLY {n} moments where a still frame from the video would genuinely help the reader — a diagram, chart, demo, on-screen text, a product, b-roll, or a striking visual.

AVOID:
- Pure talking-head shots (a person just speaking against a plain background) unless the moment is truly iconic
- Intros, outros, sponsor reads, transitions

For EACH chosen moment return:
- "timestamp": the moment as it appears in the transcript, "MM:SS" (or "H:MM:SS")
- "caption": one concise sentence (<= 15 words) describing what is shown AND why it matters to the article
- "anchor": a SHORT exact phrase copied verbatim from the ARTICLE (5-10 words) marking where this image belongs

Return ONLY a JSON array, no markdown, no code fences, no commentary.

Example:
[
  {{"timestamp": "02:15", "caption": "Bar chart showing a 40% drop in recall after one sleepless night", "anchor": "memory consolidation collapses without deep sleep"}}
]

ARTICLE:
{article}

TIMESTAMPED TRANSCRIPT:
{transcript_with_timestamps}"""


def parse_frame_moments(text):
    """Parse the model's JSON into a clean list of frame moments.

    Each returned item: {seconds, timestamp, caption, anchor}. Items missing
    a parseable timestamp, caption, or anchor are dropped. Tolerates code
    fences and truncated JSON (reuses _salvage_truncated_json).
    """
    if not text:
        return []
    text = text.strip()
    if text.startswith("```"):
        # drop first fence line and trailing fence
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = _salvage_truncated_json(text)
        except (json.JSONDecodeError, ValueError):
            return []

    if not isinstance(data, list):
        return []

    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        caption = (item.get("caption") or "").strip()
        anchor = (item.get("anchor") or "").strip()
        seconds = _mmss_to_seconds(item.get("timestamp"))
        if seconds is None or not caption or not anchor:
            continue
        out.append({
            "seconds": seconds,
            "timestamp": _seconds_to_mmss(seconds),
            "caption": caption,
            "anchor": anchor,
        })
    return out


def clamp_and_dedupe(moments, duration=None, max_n=4, min_gap=5):
    """Sort by time, drop out-of-range, collapse near-duplicates, cap count.

    - seconds < 0 dropped; seconds > duration dropped when duration is known
    - any moment within `min_gap` seconds of an already-kept one is dropped
    - at most `max_n` survive
    """
    ordered = sorted(moments, key=lambda m: m["seconds"])
    kept = []
    for m in ordered:
        s = m["seconds"]
        if s < 0:
            continue
        if duration is not None and s > duration:
            continue
        if kept and s - kept[-1]["seconds"] < min_gap:
            continue
        kept.append(m)
        if len(kept) >= max_n:
            break
    return kept


def inject_frame_markers(article_md, moments):
    """Insert ``[[FRAME:<seconds>]]`` markers into the article.

    Each marker is placed on its own line right after the paragraph that
    contains the moment's anchor phrase. If the anchor isn't found, the
    marker is appended at the end (a fallback gallery). The caption travels
    separately in the moments list — Phase 4 swaps the marker for the image.
    """
    if not moments:
        return article_md

    result = article_md
    appended = []
    for m in moments:
        marker = f"[[FRAME:{m['seconds']}]]"
        anchor = m.get("anchor", "")
        idx = result.find(anchor) if anchor else -1
        if idx == -1:
            appended.append(m)
            continue
        # find end of the paragraph containing the anchor (next blank line)
        para_break = result.find("\n\n", idx)
        if para_break == -1:
            # anchor in last paragraph — append marker at the very end
            appended.append(m)
            continue
        insert_at = para_break  # before the blank line
        result = result[:insert_at] + f"\n\n{marker}" + result[insert_at:]

    if appended:
        gallery = "\n\n".join(f"[[FRAME:{m['seconds']}]]" for m in appended)
        result = result.rstrip() + "\n\n" + gallery + "\n"

    return result


def select_frame_moments(video, article, n=4):
    """Ask Gemini to choose up to N visually valuable moments for a video.

    Returns a clamped/deduped list of {seconds, timestamp, caption, anchor}.
    Returns [] (without any API call) when no timestamped transcript exists.
    """
    from get_transcripts import format_segments_with_timestamps

    segments = video.get("transcript_segments") or []
    if not segments:
        return []

    transcript_ts = format_segments_with_timestamps(segments)
    duration = video.get("duration")
    prompt = build_frame_prompt(article, transcript_ts, n=n)

    retry_wait = 5
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(retry_wait)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=2000,
                    temperature=0.4,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            )
            _log_usage_metadata(response, label='Frame-select')
            moments = parse_frame_moments(response.text or "")
            return clamp_and_dedupe(moments, duration=duration, max_n=n)
        except Exception as e:
            error_str = str(e).lower()
            is_transient = any(msg in error_str for msg in ['503', 'overloaded', '429', 'quota', '500', 'internal server error'])
            if is_transient and attempt < MAX_RETRIES - 1:
                print(f"  [!] Frame-select API issue ({error_str[:60]}...). Retrying in {retry_wait}s...")
                retry_wait *= 2
                continue
            print(f"  [!] Failed to select frame moments: {e}")
            return []

    return []


# ---------- Daily speaking-output prompt (Phase 0 of daily-speaking-output) ----------

def build_speaking_prompt_request(article):
    """Prompt Gemini to craft ONE production-style speaking task for the day.

    This asks the learner to say their OWN one sentence, with scaffolding
    (a frame + reusable patterns) so a B1 learner can actually produce output.
    """
    body = article.get("article", "")
    if len(body) > 3000:
        body = body[:3000]
    return f"""You design a daily English speaking mini-lesson for a Korean B1 learner,
loosely inspired by the article below. The lesson teaches REUSABLE PATTERNS and
ends with the learner producing their OWN sentence — not reciting fixed text.

Build 2 PATTERNS. Each pattern is one reusable everyday sentence frame (with a
___ slot) that a learner truly uses in conversation — B1-B2, high-frequency,
never technical. For each pattern give:
- "pattern": the frame with a ___ slot.
- "pattern_ko": short Korean gloss of the frame.
- "s1": a full model sentence using that frame (shadow step). {{en, ko}}
- "s2": a DIFFERENT everyday sentence using THE SAME frame (fill step), plus
  "answer" = the word/short phrase that fills the ___ slot in s2. {{en, ko, answer}}

VARIETY IS THE TOP PRIORITY — the lesson must feel fresh, never formulaic:
- Pick frames that fit TODAY's article theme/situation, so they change as the
  topic changes, while staying everyday and natural.
- The 2 patterns MUST use DIFFERENT grammatical shapes. Do NOT make both the
  same mold. Mix across types, e.g.: a time clause ("Whenever ___, I ___"),
  a comparison ("___ is better than ___"), a phrasal verb ("I ended up ___"),
  a past habit ("I used to ___"), a suggestion ("Why don't we ___?"),
  a wish ("I wish I could ___"), a reason ("That's why I ___").
- BANNED frames — NEVER output these or ANY close variant. This bans the whole
  "It's <adjective> to ___" and "It's <adjective> for ___ to ___" mold in every
  form (hard, easy, difficult, important, nice...):
  "It's hard to ___", "It's hard for ___ to ___", "It's easy to ___",
  "I feel like ___", "I love it when ___", "I want to ___", "I need to ___",
  "I think ___", "I have to ___".
- s1 and s2 share the same frame; keep both SHORT (<= 10 words), concrete.
- DO NOT copy sentences verbatim from the article; no rare/technical words.

Then give the day's PRODUCTION TASK — the EASY payoff: the learner says ONE
simple sentence about THEIR OWN life by reusing ONE of the patterns above.
Target B1 level (the learner is building toward B1-B2) — short, concrete, one
idea, easy to say out loud. This is the goal, so it must NOT feel hard:
- "topic": short English topic label.
- "question_ko": a CONCRETE, personal question answerable in ONE short
  sentence about the learner's own daily life or experience. NOT hypothetical,
  NOT abstract — something they can answer immediately.
- "frame": take ONE of the two patterns above (whichever is easiest to use
  about oneself) and present it as the answer frame with exactly ONE ___ blank
  for the learner to fill. If that pattern has two slots, fill one in yourself
  and leave only one blank. Keep it SHORT — one clause, <= 8 words. Do NOT
  combine both patterns and do NOT add extra clauses.
- "model": one short, simple B1 model answer (<= 12 words) that fills the frame.

Return ONLY JSON. Every <...> below is an INSTRUCTION to fill with your OWN
fresh content — it is NOT an example to copy. Create the patterns FIRST, then
build the task FROM them:
{{
  "patterns": [
    {{
      "pattern": "<fresh everyday frame #1 with a ___ slot, obeying the rules>",
      "pattern_ko": "<Korean gloss>",
      "s1": {{"en": "<model sentence using frame #1>", "ko": "<Korean>"}},
      "s2": {{"en": "<different sentence, same frame #1>", "ko": "<Korean>", "answer": "<slot filler>"}}
    }},
    {{
      "pattern": "<fresh frame #2 — a DIFFERENT grammatical shape from #1>",
      "pattern_ko": "<Korean gloss>",
      "s1": {{"en": "<model sentence using frame #2>", "ko": "<Korean>"}},
      "s2": {{"en": "<different sentence, same frame #2>", "ko": "<Korean>", "answer": "<slot filler>"}}
    }}
  ],
  "topic": "<short English topic label>",
  "question_ko": "<concrete personal question, answerable in one short sentence>",
  "frame": "<ONE pattern from above with a single ___ blank, one clause, <= 8 words>",
  "model": "<short simple B1 model answer, <= 12 words>"
}}

ARTICLE TITLE: {article.get('title', '')}

ARTICLE:
{body}"""


def parse_speaking_prompt(text):
    """Parse the model JSON into a validated speaking-prompt dict, or None.

    Required: question_ko, frame, model. topic defaults to "". expressions are
    filtered to well-formed {en, ko} items and capped at 3. Tolerant of code
    fences and truncation.
    """
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = _salvage_truncated_json(text)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(data, dict):
        return None

    question = (data.get("question_ko") or "").strip()
    frame = (data.get("frame") or "").strip()
    model = (data.get("model") or "").strip()
    if not question or not frame or not model:
        return None

    def _phrase_list(key, cap):
        out = []
        for item in (data.get(key) or []):
            if not isinstance(item, dict):
                continue
            en = (item.get("en") or "").strip()
            if not en:
                continue
            out.append({"en": en, "ko": (item.get("ko") or "").strip()})
            if len(out) >= cap:
                break
        return out

    def _patterns(cap=3):
        out = []
        for item in (data.get("patterns") or []):
            if not isinstance(item, dict):
                continue
            pattern = (item.get("pattern") or "").strip()
            s1 = item.get("s1") or {}
            s2 = item.get("s2") or {}
            s1_en = (s1.get("en") or "").strip() if isinstance(s1, dict) else ""
            s2_en = (s2.get("en") or "").strip() if isinstance(s2, dict) else ""
            # a usable lesson needs the pattern + both example sentences
            if not pattern or not s1_en or not s2_en:
                continue
            out.append({
                "pattern": pattern,
                "pattern_ko": (item.get("pattern_ko") or "").strip(),
                "s1_en": s1_en,
                "s1_ko": (s1.get("ko") or "").strip(),
                "s2_en": s2_en,
                "s2_ko": (s2.get("ko") or "").strip(),
                "s2_answer": (s2.get("answer") or "").strip(),
            })
            if len(out) >= cap:
                break
        return out

    return {
        "topic": (data.get("topic") or "").strip(),
        "question_ko": question,
        "frame": frame,
        "expressions": _phrase_list("expressions", 3),
        "model": model,
        "shadow": _phrase_list("shadow", 4),
        "patterns": _patterns(3),
    }


# Overused "frames" we never want as a daily pattern. The prompt also bans
# these, but a theme-saturated article (e.g. one all about how *hard* something
# is) can still pull the model back to them — so we validate and retry.
_BANNED_PATTERN_RES = [
    re.compile(r"^it'?s\s+\w+\s+(?:to|for)\b", re.I),   # It's hard to / It's difficult for
    re.compile(r"^it\s+is\s+\w+\s+(?:to|for)\b", re.I),
    re.compile(r"^i\s+feel\s+like\b", re.I),
    re.compile(r"^i\s+want\s+to\b", re.I),
    re.compile(r"^i\s+need\s+to\b", re.I),
    re.compile(r"^i\s+have\s+to\b", re.I),
    re.compile(r"^i\s+think\b", re.I),
    re.compile(r"^i\s+love\s+it\s+when\b", re.I),
]


def _has_banned_pattern(sp):
    """True if any generated pattern uses an overused/banned frame."""
    if not sp:
        return False
    for p in (sp.get("patterns") or []):
        text = (p.get("pattern") or "").strip()
        if any(rx.search(text) for rx in _BANNED_PATTERN_RES):
            return True
    return False


def generate_speaking_prompt(en_articles):
    """Generate the day's speaking task from the first English article.

    Returns a validated dict (see parse_speaking_prompt) or None. Non-fatal:
    callers should treat None as "no speaking task today".
    """
    if not en_articles:
        return None

    article = en_articles[0]
    prompt = build_speaking_prompt_request(article)

    retry_wait = 5
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(retry_wait)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=1500,
                    temperature=0.85,
                    response_mime_type='application/json',
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            )
            _log_usage_metadata(response, label='Speaking-prompt')
            sp = parse_speaking_prompt(response.text or "")
            if _has_banned_pattern(sp) and attempt < MAX_RETRIES - 1:
                print("  [!] Speaking-prompt used a banned frame; regenerating...")
                continue
            return sp
        except Exception as e:
            error_str = str(e).lower()
            is_transient = any(msg in error_str for msg in ['503', 'overloaded', '429', 'quota', '500', 'internal server error'])
            if is_transient and attempt < MAX_RETRIES - 1:
                print(f"  [!] Speaking-prompt API issue ({error_str[:60]}...). Retrying in {retry_wait}s...")
                retry_wait *= 2
                continue
            print(f"  [!] Failed to generate speaking prompt: {e}")
            return None

    return None


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
