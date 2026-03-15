"""
Generate podcast-style audio using NotebookLM Python API.
Creates a two-host conversational podcast from newsletter articles.
"""

import io
import os
import sys
import time
from datetime import datetime

# Default focus prompt for podcast generation
DEFAULT_FOCUS_PROMPT = (
    "IMPORTANT: Discuss the articles in the EXACT order they are provided as sources. "
    "Do not rearrange or skip any article. "
    "Use simple, clear English suitable for intermediate English learners. "
    "Avoid complex idioms, jargon, or fast-paced speech. "
    "Explain key terms briefly when they first appear."
)

# Windows UTF-8 support
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


def _get_client():
    """Create NotebookLM client from cached credentials."""
    from notebooklm_tools.core.auth import load_cached_tokens
    from notebooklm_tools import NotebookLMClient

    tokens = load_cached_tokens()
    if not tokens or not tokens.cookies:
        print("  [!] No cached NotebookLM credentials. Run: nlm login")
        return None
    return NotebookLMClient(cookies=tokens.cookies, csrf_token=tokens.csrf_token)


def generate_podcast(articles, language='en', output_dir='audio'):
    """
    Generate a podcast-style audio overview using NotebookLM.

    Args:
        articles: List of article dicts with 'title', 'channel', 'article' keys
        language: 'en' or 'ko'
        output_dir: Directory to save the output audio file

    Returns:
        str | None: Path to the generated audio file, or None on failure
    """
    if not articles:
        print("  [!] No articles provided for podcast generation.")
        return None

    client = _get_client()
    if not client:
        return None

    safe_date = datetime.now().strftime('%Y%m%d')
    lang_code = "ko" if language == 'ko' else "en"
    notebook_title = f"Podcast_{safe_date}_{lang_code.upper()}"
    notebook_id = None
    using_fallback = False

    try:
        # Step 1: Find or create notebook
        print(f"  Looking for notebook: {notebook_title}")
        notebooks = client.list_notebooks()

        # Check if notebook with same title already exists (from previous run)
        for nb in notebooks:
            if nb.title == notebook_title:
                notebook_id = nb.id
                print(f"  Found existing notebook: {notebook_id}")
                # Delete existing sources to start fresh
                try:
                    sources = client.get_notebook_sources_with_types(notebook_id)
                    if sources:
                        for src in sources:
                            src_id = src.get('id') if isinstance(src, dict) else getattr(src, 'id', None)
                            if src_id:
                                client.delete_source(notebook_id, src_id)
                        print(f"  Cleared {len(sources)} existing source(s)")
                except Exception as e:
                    print(f"  [!] Could not clear sources: {e}")
                break

        # If not found, try to create new notebook
        if not notebook_id:
            print(f"  Creating new notebook: {notebook_title}")
            try:
                client.create_notebook(notebook_title)
                time.sleep(2)  # Wait for creation to propagate

                # Re-fetch notebook list
                notebooks = client.list_notebooks()
                for nb in notebooks:
                    if nb.title == notebook_title:
                        notebook_id = nb.id
                        break
            except Exception as e:
                print(f"  [!] Notebook creation failed: {e}")

        # Fallback: Use a persistent buffer notebook if creation fails
        if not notebook_id:
            FALLBACK_TITLE = "Podcast_Buffer"
            print(f"  [!] Creation failed. Looking for fallback notebook: {FALLBACK_TITLE}")
            for nb in notebooks:
                if nb.title == FALLBACK_TITLE:
                    notebook_id = nb.id
                    using_fallback = True
                    print(f"  Found fallback notebook: {notebook_id}")
                    # Clear existing sources
                    try:
                        sources = client.get_notebook_sources_with_types(notebook_id)
                        if sources:
                            for src in sources:
                                src_id = src.get('id') if isinstance(src, dict) else getattr(src, 'id', None)
                                if src_id:
                                    client.delete_source(notebook_id, src_id)
                            print(f"  Cleared {len(sources)} existing source(s)")
                    except Exception:
                        pass
                    break

        if not notebook_id:
            print("  [!] No notebook available. Please create 'Podcast_Buffer' manually in NotebookLM.")
            print("      https://notebooklm.google.com/")
            return None
        print(f"  Using notebook: {notebook_id}")

        # Step 2: Add articles as text sources
        print(f"  Adding {len(articles)} article(s) as sources...")
        for i, article in enumerate(articles):
            title = article.get('title', f'Article {i+1}')
            channel = article.get('channel', 'Unknown')
            body = article.get('article', '')
            source_text = f"# {title}\nChannel: {channel}\n\n{body}"

            try:
                client.add_text_source(notebook_id, text=source_text, title=f"{title} ({channel})")
                print(f"    [{i+1}/{len(articles)}] Added: {title[:50]}")
            except Exception as e:
                print(f"    [{i+1}/{len(articles)}] Failed: {e}")

        # Wait for sources to be processed
        print("  Waiting for sources to be processed...")
        time.sleep(10)

        # Step 3: Generate audio overview
        podcast_format = os.getenv("NOTEBOOKLM_PODCAST_FORMAT", "brief")
        podcast_length = os.getenv("NOTEBOOKLM_PODCAST_LENGTH", "short")
        bcp47_lang = "ko-KR" if language == 'ko' else "en-US"

        focus_prompt = os.getenv("NOTEBOOKLM_FOCUS_PROMPT", DEFAULT_FOCUS_PROMPT)

        print(f"  Generating podcast (format={podcast_format}, length={podcast_length})...")
        if focus_prompt:
            print(f"  Focus prompt: {focus_prompt[:80]}...")
        # Map string config to int codes
        FORMAT_MAP = {"deep_dive": 1, "brief": 2, "critique": 3, "debate": 4}
        LENGTH_MAP = {"short": 1, "default": 2, "long": 3}
        fmt_code = FORMAT_MAP.get(podcast_format, 1)
        len_code = LENGTH_MAP.get(podcast_length, 2)

        try:
            client.create_audio_overview(
                notebook_id,
                format_code=fmt_code,
                length_code=len_code,
                language=bcp47_lang,
                focus_prompt=focus_prompt,
            )
        except Exception as e:
            print(f"  [!] Audio creation call: {e}")
            # May still have started - continue to poll

        # Step 4: Poll for completion (max 15 minutes)
        max_wait = 900
        poll_interval = 20
        elapsed = 0
        audio_ready = False

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            print(f"  Waiting... ({elapsed}s / {max_wait}s)")

            try:
                status = client.poll_studio_status(notebook_id)
                if status:
                    for item in status:
                        item_type = item.get('type', '') if isinstance(item, dict) else ''
                        item_status = item.get('status', '') if isinstance(item, dict) else ''
                        if 'audio' in str(item_type).lower():
                            print(f"    Audio status: {item_status}")
                            if item_status == 'completed':
                                audio_ready = True
                                break
                            elif item_status == 'failed':
                                print("  [!] Audio generation failed.")
                                return None
                if audio_ready:
                    break
            except Exception as e:
                err_msg = str(e)
                print(f"  [!] Poll error: {e}")
                if 'Authentication expired' in err_msg or 'RPC Error 16' in err_msg:
                    print("  [!] Re-authenticating...")
                    client = _get_client()
                    if not client:
                        print("  [!] Re-authentication failed. Aborting.")
                        return None

        if not audio_ready:
            print(f"  [!] Podcast generation timed out after {max_wait}s.")
            print(f"  [!] Notebook kept for manual check: {notebook_id}")
            print(f"      https://notebooklm.google.com/notebook/{notebook_id}")
            return None

        # Step 5: Download audio
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"Podcast_{safe_date}_{lang_code.upper()}.m4a")
        print(f"  Downloading podcast audio...")

        try:
            import asyncio
            # Re-authenticate before download in case token expired during polling
            client = _get_client()
            if not client:
                print("  [!] Re-authentication failed before download.")
                return None
            asyncio.run(client.download_audio(notebook_id, output_path=output_path))
        except Exception as e:
            print(f"  [!] Download error: {e}")
            print(f"  [!] Notebook kept: {notebook_id}")
            return None

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"  Podcast downloaded: {output_path} ({size_mb:.1f} MB)")

            # Compress if file exceeds Gmail's 25MB limit
            MAX_EMAIL_SIZE_MB = 24  # Keep under 25MB with margin
            final_path = output_path

            if size_mb > MAX_EMAIL_SIZE_MB:
                import shutil
                import subprocess

                if shutil.which("ffmpeg"):
                    mp3_path = output_path.replace('.m4a', '.mp3')
                    # Calculate target bitrate to fit under limit
                    # Estimate: 1 minute audio at 128kbps ≈ 1MB
                    # For 24MB max, use 64kbps for safety (podcast is voice, not music)
                    print(f"  Compressing to MP3 (target: <{MAX_EMAIL_SIZE_MB}MB)...")
                    try:
                        result = subprocess.run(
                            ["ffmpeg", "-y", "-i", output_path,
                             "-codec:a", "libmp3lame", "-b:a", "64k",
                             "-ac", "1",  # mono for voice
                             mp3_path],
                            capture_output=True, text=True
                        )
                        if result.returncode == 0 and os.path.exists(mp3_path):
                            mp3_size = os.path.getsize(mp3_path) / (1024 * 1024)
                            print(f"  Compressed: {mp3_path} ({mp3_size:.1f} MB)")
                            # Remove original m4a
                            os.remove(output_path)
                            final_path = mp3_path
                        else:
                            print(f"  [!] Compression failed: {result.stderr[:200]}")
                    except Exception as e:
                        print(f"  [!] Compression error: {e}")
                else:
                    print(f"  [!] ffmpeg not found. File may be too large for email attachment.")

            # Clean up: only delete dated notebooks, keep the persistent buffer
            if not using_fallback and notebook_id:
                print(f"  Cleaning up notebook: {notebook_id}")
                try:
                    client.delete_notebook(notebook_id)
                except Exception:
                    pass
            else:
                print(f"  Keeping Podcast_Buffer for future use")

            return final_path
        else:
            print(f"  [!] Download failed or file is empty.")
            print(f"  [!] Notebook kept: {notebook_id}")
            return None

    except Exception as e:
        print(f"  [!] Podcast generation error: {e}")
        if notebook_id:
            print(f"  [!] Notebook kept for manual check: {notebook_id}")
        return None


if __name__ == "__main__":
    test_articles = [
        {
            "title": "Test Article",
            "channel": "Test Channel",
            "url": "https://youtube.com/watch?v=test",
            "article": "This is a test article about artificial intelligence and its impact on society. "
                       "AI is transforming how we work, learn, and communicate with each other. "
                       "Recent advances in large language models have enabled new applications "
                       "in education, healthcare, and creative work."
        }
    ]
    result = generate_podcast(test_articles, language='en', output_dir='audio')
    if result:
        print(f"\nSuccess! Podcast saved to: {result}")
    else:
        print("\nFailed to generate podcast.")
