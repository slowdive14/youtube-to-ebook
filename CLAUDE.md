# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube to Ebook transforms YouTube videos into magazine-style EPUB ebooks. It fetches videos from configured channels, extracts transcripts, generates bilingual articles (English + Korean) using Google Gemini AI, and delivers them via email with EPUB attachments.

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
(channel videos)  (robust extraction)      (article gen)      (EPUB + email)
```

**main.py** orchestrates the entire pipeline and integrates with **video_tracker.py** to avoid reprocessing videos.

**dashboard.py** provides a Streamlit web UI for managing channels, customizing prompts, generating newsletters, and viewing archive.

### Key Data Flow

1. `channels.txt` - List of YouTube channel handles (one per line, e.g., `@hubermanlab`)
2. `processed_videos.json` - Tracks processed video IDs to prevent duplicates
3. `newsletters/` - Archive of generated HTML and EPUB files with metadata JSON

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

## Documentation Requirements

### FORSLOWDIVE.md
For every project, write a detailed `FORSLOWDIVE.md` file that explains the whole project in plain language.

**Required sections:**
- Technical architecture and how the system works
- Codebase structure and how the various parts are connected
- Technologies used and why we made these technical decisions
- Lessons learned:
  - Bugs we ran into and how we fixed them
  - Potential pitfalls and how to avoid them in the future
  - New technologies used
  - How good engineers think and work
  - Best practices

**Writing style:**
- Make it engaging to read, not like boring technical documentation or a textbook
- Use analogies and anecdotes to make concepts understandable and memorable
- Write in plain language that anyone can follow
- Use ASCII characters for diagrams (`+`, `-`, `|`, `>`, `v`) instead of Unicode box-drawing characters for better compatibility
