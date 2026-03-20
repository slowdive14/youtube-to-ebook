"""
Step 4b: Export Newsletter to Archive
Uploads MP3 audio to Cloudflare R2, generates issue markdown,
and pushes to the archive site repository.
"""

import sys
import io

# Fix Windows console encoding for Unicode characters
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "youtube-digest-audio")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")  # e.g. https://pub-xxx.r2.dev

# Archive repo path
ARCHIVE_REPO_PATH = os.getenv("ARCHIVE_REPO_PATH", "")


def _get_r2_client():
    """Create a boto3 S3 client configured for Cloudflare R2."""
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def upload_audio_to_r2(local_path):
    """
    Upload an MP3 file to Cloudflare R2.
    Returns the public URL of the uploaded file.
    Key format: audio/YYYY/MM/DD/filename.mp3
    """
    if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_URL]):
        print("  [!] R2 credentials not configured. Skipping audio upload.")
        return None

    if not os.path.exists(local_path):
        print(f"  [!] Audio file not found: {local_path}")
        return None

    now = datetime.now()
    filename = os.path.basename(local_path)
    key = f"audio/{now.strftime('%Y/%m/%d')}/{filename}"

    try:
        client = _get_r2_client()
        print(f"  Uploading {filename} to R2...")
        client.upload_file(
            local_path,
            R2_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": "audio/mpeg"},
        )
        public_url = f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
        print(f"  [OK] Uploaded: {public_url}")
        return public_url
    except Exception as e:
        print(f"  [!] R2 upload failed: {e}")
        return None


def generate_issue_markdown(en_articles, ko_articles, audio_urls, subject=None, drill_sentences=None):
    """
    Generate a markdown file with YAML frontmatter for the archive site.

    Returns (filename, content) tuple.
    Frontmatter: title, date, subject, audioUrls, articles array, drillSentences.
    Body: English articles + divider + Korean articles.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    filename = f"{date_str}.md"

    # Build subject line
    if not subject:
        if en_articles:
            first_title = en_articles[0]["title"]
            count = len(en_articles)
            if count > 1:
                subject = f"{first_title} & {count - 1} more"
            else:
                subject = first_title
        else:
            subject = f"YouTube Digest {date_str}"

    # Build articles metadata for frontmatter
    articles_meta = []
    for a in (en_articles or []):
        articles_meta.append(
            f'  - title: "{_escape_yaml(a["title"])}"\n'
            f'    channel: "{_escape_yaml(a["channel"])}"\n'
            f'    url: "{a["url"]}"'
        )

    # Build audio URLs for frontmatter
    audio_lines = ""
    if audio_urls:
        audio_lines = "audioUrls:\n"
        for url in audio_urls:
            audio_lines += f'  - "{url}"\n'

    articles_yaml = "articles:\n" + "\n".join(articles_meta) if articles_meta else ""

    # Build drill sentences for frontmatter
    drill_lines = ""
    if drill_sentences:
        drill_lines = "drillSentences:\n"
        for ds in drill_sentences:
            drill_lines += (
                f'  - sentence: "{_escape_yaml(ds["sentence"])}"\n'
                f'    korean: "{_escape_yaml(ds["korean"])}"\n'
                f'    blank: "{_escape_yaml(ds["blank"])}"\n'
                f'    blank_answer: "{_escape_yaml(ds["blank_answer"])}"\n'
                f'    swap_word: "{_escape_yaml(ds["swap_word"])}"\n'
            )

    # Frontmatter
    frontmatter = (
        f"---\n"
        f'title: "YouTube Digest — {date_str}"\n'
        f"date: {date_str}\n"
        f'subject: "{_escape_yaml(subject)}"\n'
        f"{audio_lines}"
        f"{articles_yaml}\n"
        f"{drill_lines}"
        f"---\n"
    )

    # Body: English articles
    body_parts = []

    if en_articles:
        body_parts.append("## English\n")
        for i, a in enumerate(en_articles):
            if i > 0:
                body_parts.append("\n---\n")
            body_parts.append(
                f'> Based on **"{a["title"]}"** from **{a["channel"]}**\n'
                f'> [Watch the original video]({a["url"]})\n\n'
            )
            body_parts.append(a["article"])
            body_parts.append("\n")

    if en_articles and ko_articles:
        body_parts.append("\n---\n\n")

    if ko_articles:
        body_parts.append("## 한국어\n")
        for i, a in enumerate(ko_articles):
            if i > 0:
                body_parts.append("\n---\n")
            body_parts.append(
                f'> **"{a["title"]}"** — **{a["channel"]}** 기반 기사\n'
                f'> [원본 영상 보기]({a["url"]})\n\n'
            )
            body_parts.append(a["article"])
            body_parts.append("\n")

    content = frontmatter + "\n" + "".join(body_parts)
    return filename, content


def _escape_yaml(s):
    """Escape double quotes in YAML string values."""
    return s.replace('"', '\\"')


def push_to_archive_repo(content, filename):
    """
    Save the issue markdown to the archive repo and git push.
    Target: ARCHIVE_REPO_PATH/src/content/issues/<filename>
    """
    if not ARCHIVE_REPO_PATH:
        print("  [!] ARCHIVE_REPO_PATH not configured. Skipping git push.")
        return False

    repo_path = Path(ARCHIVE_REPO_PATH)
    issues_dir = repo_path / "src" / "content" / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    filepath = issues_dir / filename
    base_name = filepath.stem
    ext = filepath.suffix
    counter = 2
    
    # Ensure unique filename so we don't overwrite multiple runs on the same day
    while filepath.exists():
        filename = f"{base_name}_{counter:02d}{ext}"
        filepath = issues_dir / filename
        counter += 1

    filepath.write_text(content, encoding="utf-8")
    print(f"  [OK] Issue saved: {filepath}")

    # Git add, commit, push
    try:
        subprocess.run(
            ["git", "add", str(filepath)],
            cwd=str(repo_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"Add issue {filename}"],
            cwd=str(repo_path), check=True, capture_output=True,
        )
        # Pull latest remote changes (rebase) before pushing to handle diverged branches
        subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=str(repo_path), check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=str(repo_path), check=True, capture_output=True,
        )
        print(f"  [OK] Pushed to archive repo")
        return True
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(f"  [!] Git operation failed: {stderr[:200]}")
        return False


def export_newsletter_issue(en_articles, ko_articles, audio_paths_en=None, audio_paths_ko=None, drill_sentences=None):
    """
    Main entry point for archive export.
    1. Upload audio files to R2
    2. Generate issue markdown
    3. Push to archive repo
    """
    print("\n[STEP 4b] Exporting to archive...")

    # 1. Upload audio to R2
    audio_urls = []
    for paths in [audio_paths_en or [], audio_paths_ko or []]:
        for path in paths:
            url = upload_audio_to_r2(path)
            if url:
                audio_urls.append(url)

    # 2. Generate issue markdown
    filename, content = generate_issue_markdown(
        en_articles, ko_articles, audio_urls, drill_sentences=drill_sentences
    )

    # 3. Push to archive repo
    push_to_archive_repo(content, filename)

    print("  [OK] Archive export complete\n")
