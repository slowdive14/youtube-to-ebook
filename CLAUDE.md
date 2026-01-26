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

### Duplication & Concurrency (main.py)
- Uses `video_tracker.py` to skip already-processed video IDs.
- **Execution Lock**: Creates `main.lock` during runtime to prevent simultaneous executions (fixing duplicate email bug).

### EPUB Creation
Uses `ebooklib` to create properly formatted EPUB with table of contents and CSS styling.

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
