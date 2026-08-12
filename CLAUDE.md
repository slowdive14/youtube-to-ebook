# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube to Ebook transforms YouTube videos into magazine-style articles. It fetches videos from configured channels, extracts transcripts, generates bilingual articles (English + Korean) using Google Gemini AI, and delivers them via email with dynamic subject lines.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run full pipeline (fetch videos, transcripts, generate articles, send email)
python main.py
# Or on Windows:
py main.py

# Process a specific video URL (bypasses channel list and history)
python main.py --url "https://www.youtube.com/watch?v=VIDEO_ID"

# Launch web dashboard (Streamlit)
python dashboard.py
# Or: streamlit run dashboard.py
```

## Architecture

The pipeline flows through four sequential stages:

```
get_videos.py --> get_transcripts.py --> write_articles.py --> send_email.py
     |                   |                      |                    |
     v                   v                      v                    v
YouTube API      API + Selenium Fallback     Gemini AI          Gmail SMTP
(channel videos)  (robust extraction)      (article gen)     (Dynamic Subject)
```

**main.py** orchestrates the entire pipeline and integrates with **video_tracker.py** to avoid reprocessing videos.

**dashboard.py** provides a Streamlit web UI for managing channels, customizing prompts, and generating newsletters manually.

### Key Data Flow

1. `channels.txt` - List of YouTube channel handles (one per line, e.g., `@hubermanlab`)
2. `processed_videos.json` - Tracks processed video IDs to prevent duplicates
3. [DISABLED] `newsletters/` - Local archiving is disabled to keep the system lightweight. All content is delivered directly to email.

## Environment Variables

Required in `.env` file (copy from `.env.example`):
- `YOUTUBE_API_KEY` - YouTube Data API v3 key
- `GEMINI_API_KEY` - Google Gemini API key
- `GMAIL_ADDRESS` - Gmail address for sending newsletters (optional)
- `GMAIL_APP_PASSWORD` - Gmail app password (optional)
- `ENABLE_FRAME_CAPTURE` - `true` to extract & embed video frames inline (default off)
- `FRAMES_PER_VIDEO` - frames to extract per video when capture is on (default 4)

## Important Implementation Details

### Shorts Detection
Videos are checked against `/shorts/` URL pattern via HEAD request, not duration. This is necessary because some Shorts exceed 60 seconds.

### Transcript Fetching (get_transcripts.py)
- **Hybrid Approach**: First attempts fast extraction via `youtube-transcript-api`.
- **Selenium Fallback**: If IP blocked (429 error), automatically launches headless Chrome via Selenium.
- **Robust Scrape**: Uses global `innerText` + regex timestamp matching to extract content even if DOM selectors change or are hidden in Shadow DOM.
- Forces `hl=en` in browser requests for consistent UI element identification.

### Article Generation (write_articles.py)
- Uses `gemini-3-flash-preview` model.
- `max_output_tokens` set to 8000 for comprehensive bilingual summaries.
- 15-second delay between API calls with retry logic.

### Daily Curation (select_videos.py) — Step 1c
The channel list yields 6-9 new videos a day, which is more reading than anyone finishes and ~6 free-tier API requests each. Step 1c labels the day's **titles** by subject and keeps `MAX_ARTICLES_PER_DAY` (default 3).
- Selection is by **subject spread, not topic preference**: one video per area (technology / science / health / business / politics / culture / other), taken in channel-list order, so a day reads as tech + health + culture rather than three takes on the same news cycle. Only once every area present is represented does a second from the same one get in.
- ⚠️ An earlier version scored videos for *technology relevance* and applied a `MIN_TOPIC_SCORE` floor that dropped politics and economics outright. That was replaced on request — no topic is privileged now, and the floor is gone. Don't reintroduce a preference ranking; the buckets are coarse on purpose, because finer ones (AI vs software) would split near-identical videos into "different" domains and defeat the spread.
- Runs **before transcripts**, so a dropped video costs nothing beyond the one classification call — it saves a transcript fetch plus ~6 Gemini requests.
- Falls back to a keyword heuristic (`_heuristic_domain`) if the API call fails, so the digest never dies on a classification error.
- Unselected videos are **not** marked processed, so they stay eligible until their channel posts something newer and can appear on a slower day.

### Summary-First Reading (archive site)
An issue is 6 episodes × 2 languages, so the full text is far too long to scroll. Every section therefore shows **only a one-line summary**; clicking it opens the full text. Reading the summary lines top-to-bottom is meant to convey the whole issue — that's the contract the generation prompt is written against.
- **Generation**: `write_articles.generate_section_summaries(article_md, language)` — one Gemini call per article returning `{heading: summary}`. Stored on `article['section_summaries']`.
- **Markers**: `export_archive._render_article_body` calls `inject_section_summaries()` **last** (after frame embedding, so no frame anchor can match inside a summary line), writing `[[SUM]] …` under each heading. The canonical `article['article']` stays marker-free so email/audio never read markers — same rule as `[[FRAME:…]]`.
- **Rendering**: `src/plugins/rehype-collapsible-sections.mjs` (wired in `astro.config.mjs`) turns heading + `[[SUM]]` + body into `heading` + `<details class="sec">`. Headings stay **outside** the `<details>` — the TOC, scroll-spy IntersectionObserver, and English/한국어 wrapper all walk them and need them visible and direct children.
- **No marker?** Older issues fall back to promoting the section's first paragraph. Fill them in with `py scripts/backfill_section_summaries.py [--limit N]` (resumable, skips files that already have markers).
- Article titles (H1) and the language dividers are never collapsed; `extract_section_headings` drops them so no stray marker can render.
- The issue page has an `전체 펼치기/접기` toggle, and TOC/hash navigation auto-opens the target section.

### Read-Aloud Feed for Velora (`/api/reading`)
Velora (`C:\Users\user\Downloads\velora`, a separate repo) has a 낭독 screen whose material was manually pasted. This endpoint feeds it the newest issue automatically.
- Serves the newest issue's episodes as **per-episode summaries** (~130-180 words, 1-2 min each), not full articles — a 3,000-word article is a 25-minute read-aloud nobody sustains daily. Velora lists all ~6 and the learner picks one.
- **Runtime route** (`prerender = false`), not a prerendered `.json`: Velora is a different origin and needs `Access-Control-Allow-Origin`, which a static file can't carry — the Vercel adapter's Build Output config ignores `vercel.json` headers.
- Reads `articles[].summary` from frontmatter, so `summary` had to be added to the `content.config.ts` schema (Zod strips unknown keys — it was in the markdown but invisible to the site).

### Podcast Audio (generate_podcast.py) — currently OFF
- ⚠️ Audio is **disabled**: `main.py` skips generation unless `ENABLE_PODCAST=true`, and `src/config.ts` `FEATURES.audio` hides the player + "Audio Available" badge. No code was removed — flip both to restore.
- `run_daily.bat` reads the same `ENABLE_PODCAST` from `.env` and skips its **NotebookLM auth pre-flight** when off. That pre-flight is the one that hangs a scheduled run forever: `nlm login` opens Chrome and blocks on a human. Gating `main.py` alone is not enough — the launcher runs before it. `FEATURES.readerMode` likewise hides the `/read` page's link (the page itself still builds).
- NotebookLM generates the newsletter audio. To avoid episodes blending together, articles are split into **per-episode groups** (`generate_podcasts_grouped`) — one podcast per group — instead of one bundled podcast.
- NotebookLM **free plan caps Audio Overviews at 3/day**, so the digest is split into at most `NOTEBOOKLM_DAILY_AUDIO_LIMIT` (default 3) groups; with more videos than the cap, the earliest groups bundle the extras. Each group's podcast becomes a separate "Part N" player on the archive site (the pipeline already supports a list of `audioUrls`).
- Per-group length defaults to `NOTEBOOKLM_GROUP_LENGTH=default` (~10 min); a few groups still add up to a substantial total.

### Daily Speaking Output ("오늘의 한 마디")
Replaces the unused, recitation-style Speaking Drill with a daily **production** task: the learner speaks ONE original sentence and gets AI coaching. The old Web Speech recognition was the blocker (weak on Korean-accented English, flaky on mobile, exact-match grading), so it's gone entirely.
- **Prompt**: `write_articles.generate_speaking_prompt(en_articles)` makes one production prompt per digest (Korean question + sentence frame + 2-3 reusable expressions from the article + a model answer) → frontmatter `speakingPrompt` (schema in `content.config.ts`).
- **Recognition**: the `/speak/<issue>` page records audio with **MediaRecorder** (no browser SpeechRecognition) and POSTs it to the **`/api/speak-feedback`** serverless route, which sends the audio to **Gemini** (`inlineData` + `responseMimeType: application/json`) and returns `{transcript, good, corrected, upgrade, model_answer}`. Gemini handles accents far better and there's **no pass/fail gate** — recognition errors become coaching, not failure.
- **One recording, not eight.** Stage 1 is **read-and-listen only** (`maxStep: 2` — example, then the same pattern with a blank + 정답 보기). It used to demand a recording at each of 2 patterns × 3 steps, and `다음 단계` only appeared *after* Gemini answered, so Stage 2 was gated behind 6 clips — on a page called "오늘의 한 마디". Speaking now happens once, where it's the point.
- **Typing is a first-class alternative**: `/api/speak-feedback` accepts `text` instead of `audioBase64` (`WRITTEN_PROMPT`, no `inlineData` part; everything downstream is shared). Most of the day you can't talk to your phone, and a task you can only do alone at home isn't a daily habit.
- **Habit loop**: issue page shows a prominent `🎤 오늘의 한 마디` CTA; the page tracks a streak (`🔥 N일`, local-calendar-day based) and a per-day sentence log in localStorage.
- ⚠️ **Never put an example frame in the prompt.** Listing one frame per grammatical category to encourage variety did the opposite — the model copied them, and `That's why I ___` shipped in 8 of 14 issues (also `I used to ___` ×4, `I ended up ___` ×3, all straight from the list). Name the *categories* only. Same failure mode as the original worked-example bug.
- **Anti-repetition**: `export_archive.recent_speaking_patterns()` reads the last 8 issues' frames and `main.py` passes them as `avoid=`. They go into the prompt as "already used" and `_has_banned_pattern(sp, avoid)` rejects a reuse (retry). Matching is by `pattern_stem()` — the frame's first two words — because the repetition happened at the family level (`I used to ___` vs `I used to ___ every day`), not the exact-string level.
- ⚠️ **Deploy**: site changes need `trigger_vercel_deploy()` (Vercel uses a Deploy Hook, not auto-deploy on push). `GEMINI_API_KEY` must be set in Vercel env (already used by `api/define.ts`).

### Duplication & Concurrency (main.py)
- Uses `video_tracker.py` to skip already-processed video IDs.
- **Execution Lock**: Creates `main.lock` during runtime to prevent simultaneous executions (fixing duplicate email bug).

### EPUB Creation
Uses `ebooklib` to create properly formatted EPUB with table of contents and CSS styling.

### Video Frame Capture (capture_frames.py, opt-in) — currently OFF
⚠️ `ENABLE_FRAME_CAPTURE=false`. It was the pipeline's most expensive stage by far: frame-selection alone was **42% of all input tokens** (178K of 422K on the 2026-08-04 run, one video costing 89K because the whole timestamped transcript is sent), plus 7 requests per video (1 select + 6 vision picks, 4 images each). That's the difference between 13 and 6 requests per video on a free-tier key.

When `ENABLE_FRAME_CAPTURE=true`, the pipeline embeds representative screenshots inline in each article:
1. **Timestamps**: `get_transcripts.py` preserves `transcript_segments` ({start, text}) from the transcript API.
2. **Moment selection**: `write_articles.select_frame_moments()` asks Gemini for the N most visually valuable moments (avoiding talking-head shots), returning timestamp + caption + an article anchor phrase.
3. **Extraction**: `capture_frames.py` downloads the video once via **yt-dlp with `player_client=android`** (the default web client serves DASH/AV1 URLs that 403; android serves the progressive format 18) then `ffmpeg -ss` extracts a candidate window per moment.
4. **Vision pick**: Gemini Vision selects the clearest candidate frame (falls back to the exact-timestamp frame).
5. **Embed**: `export_archive.py` uploads frames to R2 (`images/YYYY/MM/DD/`) and swaps `[[FRAME:<seconds>]]` markers for `![caption](url)`. The canonical `article['article']` stays marker-free, so audio/email never read markers.
Fully isolated — any failure leaves the digest untouched. See `docs/plans/PLAN_video-frame-capture.md`.

### Windows Compatibility
All Python files wrap stdout/stderr with UTF-8 encoding to handle Unicode characters on Windows console.

## Development Lessons & Best Practices

### 1. Cross-Platform Environment Handling
- **Problem**: Hardcoded commands like `py` fail on Linux (Streamlit Cloud), and `python3` may fail on Windows.
- **Solution**: Always use `sys.executable` when launching subprocesses to ensure the exact same Python environment and dependencies are preserved across all platforms.

### 2. Concurrency & Duplicate Prevention
- **Problem**: UI-driven applications (Streamlit) can trigger the same backend process multiple times via rapid clicks or automatic reruns, causing duplicate actions (like sending 3 emails).
- **Solution**: Implement a sentinel lock file (e.g., `main.lock`) at the start of critical long-running processes. Always use a `try...finally` block to ensure the lock is released.

### 3. Selenium in Cloud Environments
- **Problem**: Selenium requires both Python libraries (`requirements.txt`) and system-level binaries (`packages.txt`). Standard `webdriver-manager` often fails in restricted Cloud shells.
- **Solution**: 
    - Include `chromium` and `chromium-driver` in `packages.txt`.
    - Configure Selenium with `--headless=new`, `--no-sandbox`, and `--disable-dev-shm-usage`.
    - Manually detect standard Linux paths (e.g., `/usr/bin/chromium`) if the automatic manager fails.

### 4. Robust Web Scraping (YouTube Case)
- **Problem**: Modern web apps use Shadow DOM and frequently change CSS classes, making specific selectors brittle.
- **Solution**: Use broader extraction methods such as global `document.body.innerText` combined with Regex pattern matching (e.g., searching for `\d+:\d+` timestamps) for higher reliability.

### 5. API Resilience
- **Problem**: LLM APIs (Gemini) frequently return transient errors like `503 Service Unavailable` or `429 Too Many Requests`.
- **Solution**: Implement **Exponential Backoff** (e.g., 5s, 10s, 20s...) rather than simple fixed-interval retries to respect server load and ensure task completion.

### 6. Windows Unicode Support
- **Problem**: Windows console often defaults to non-UTF8 encodings, causing crashes when printing Unicode characters (Korean, Emojis).
- **Solution**: Always wrap `sys.stdout` and `sys.stderr` with `io.TextIOWrapper` using `utf-8` encoding at the entry point of every script.

### 7. Lean Delivery & UI Simplification
- **Insight**: Local archiving (EPUB/HTML) and "Archive" UI tabs can add unnecessary complexity if the primary consumption is via email.
- **Action**: Removed local file generation and the corresponding Dashboard tab to focus on a "Lean" workflow where content is generated and delivered immediately without leaving artifacts on the server.

### 8. Dynamic Email Engagement
- **Improvement**: Static email subjects (e.g., "YouTube Digest - Date") are less engaging and hard to search.
- **Solution**: Constructed dynamic subjects using the title of the first video and a total count (e.g., "[Title] 외 2건 | YouTube 다이제스트").

## Documentation Requirements
... (remains same)
