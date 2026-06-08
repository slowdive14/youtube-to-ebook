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
import re
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

# R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "youtube-digest-audio")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")  # e.g. https://pub-xxx.r2.dev

# Archive repo path
ARCHIVE_REPO_PATH = os.getenv("ARCHIVE_REPO_PATH", "")

# Vercel Deploy Hook (explicit rebuild trigger, independent of GitHub auto webhook)
VERCEL_DEPLOY_HOOK_URL = os.getenv("VERCEL_DEPLOY_HOOK_URL", "")


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

    return _upload_to_r2(local_path, key, "audio/mpeg")


def upload_image_to_r2(local_path):
    """
    Upload an image (JPEG) frame to Cloudflare R2.
    Returns the public URL, or None if R2 isn't configured / upload fails.
    Key format: images/YYYY/MM/DD/filename.jpg
    """
    if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_URL]):
        print("  [!] R2 credentials not configured. Skipping image upload.")
        return None
    if not os.path.exists(local_path):
        print(f"  [!] Image file not found: {local_path}")
        return None

    now = datetime.now()
    filename = os.path.basename(local_path)
    key = f"images/{now.strftime('%Y/%m/%d')}/{filename}"
    return _upload_to_r2(local_path, key, "image/jpeg")


def _upload_to_r2(local_path, key, content_type):
    """Shared R2 put: upload local_path to `key` with the given Content-Type."""
    try:
        client = _get_r2_client()
        filename = os.path.basename(local_path)
        print(f"  Uploading {filename} to R2...")
        client.upload_file(
            local_path,
            R2_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        public_url = f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
        print(f"  [OK] Uploaded: {public_url}")
        return public_url
    except Exception as e:
        print(f"  [!] R2 upload failed: {e}")
        return None


def generate_issue_markdown(en_articles, ko_articles, audio_urls, subject=None, drill_sentences=None, frame_map=None):
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

    # Build articles metadata for frontmatter (with per-episode summary)
    articles_meta = []
    for a in (en_articles or []):
        entry = (
            f'  - title: "{_escape_yaml(a["title"])}"\n'
            f'    channel: "{_escape_yaml(a["channel"])}"\n'
            f'    url: "{a["url"]}"'
        )
        summary = (a.get("summary") or "").strip()
        if summary:
            # YAML folded scalar: single newlines become spaces, blank lines
            # become paragraph breaks. Preserve blank lines so multi-paragraph
            # summaries render correctly in the archive site.
            indented_lines = []
            for line in summary.splitlines():
                if line.strip():
                    indented_lines.append("      " + line.rstrip())
                else:
                    indented_lines.append("")  # blank line preserved
            indented = "\n".join(indented_lines)
            entry += f'\n    summary: >-\n{indented}'
        articles_meta.append(entry)

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
            article_md = _render_article_body(a, summary_label="Episode summary", global_frame_map=frame_map)
            body_parts.append(article_md)
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
            article_md = _render_article_body(a, summary_label="에피소드 요약", global_frame_map=frame_map)
            body_parts.append(article_md)
            body_parts.append("\n")

    content = frontmatter + "\n" + "".join(body_parts)
    return filename, content


def _render_article_body(article, summary_label, global_frame_map=None):
    """Build one article's markdown body: headings -> summary -> frames.

    Frame handling keeps the canonical ``article['article']`` clean of
    ``[[FRAME:..]]`` markers (so audio/email never read them):
      - If the article carries ``frame_moments`` + ``frame_map``, markers are
        injected here (from anchors) and immediately swapped for images.
      - Otherwise we fall back to ``global_frame_map`` and embed any markers
        already present in the text (covers the simple/global test path).
    """
    md = _normalize_article_headings(article["article"], fallback_title=article["title"])
    md = _inject_summary_after_h1(md, article.get("summary", ""), label=summary_label)

    moments = article.get("frame_moments")
    fmap = article.get("frame_map") or global_frame_map
    if moments and fmap:
        # late import: avoids a hard dependency when frame capture is unused
        from write_articles import inject_frame_markers
        md = inject_frame_markers(md, moments)
    md = embed_frames(md, fmap)
    return md


_FRAME_MARKER_RE = re.compile(r'\[\[FRAME:(\d+)\]\]')


def embed_frames(article_md, frame_map):
    """Replace ``[[FRAME:<seconds>]]`` markers with markdown images.

    `frame_map` maps seconds -> (image_url, caption). Each marker whose
    seconds is in the map becomes an image + a visible italic caption.
    Markers with no map entry (frame failed to capture/upload) are stripped
    so no literal ``[[FRAME:..]]`` ever leaks to the reader. Frames in the
    map that have no marker in the text are appended as an end gallery.
    """
    if not article_md:
        return article_md
    frame_map = frame_map or {}
    used = set()

    def _img(url, caption):
        cap = (caption or "").strip()
        if cap:
            return f"![{cap}]({url})\n\n*{cap}*"
        return f"![]({url})"

    def repl(m):
        secs = int(m.group(1))
        if secs in frame_map:
            used.add(secs)
            url, caption = frame_map[secs]
            return _img(url, caption)
        return ""  # orphan marker -> remove

    result = _FRAME_MARKER_RE.sub(repl, article_md)

    # Append any mapped frames that had no marker, as a trailing gallery
    leftover = [s for s in frame_map if s not in used]
    if leftover:
        gallery = "\n\n".join(_img(*frame_map[s]) for s in leftover)
        result = result.rstrip() + "\n\n" + gallery + "\n"

    # Collapse blank-line gaps left by stripped markers
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result


_FENCE_RE = re.compile(r'(```[\s\S]*?```)')
_HEADING_RE = re.compile(r'^(#{1,6})([^\S\n].*)$', re.MULTILINE)


def _inject_summary_after_h1(article_text, summary, label='Episode summary'):
    """Insert ``### {label}`` + summary body right after the article's first H1.

    The archive site builds its TOC via ``querySelectorAll('h1, h2, h3')``.
    Putting the summary as an H3 (instead of a bold paragraph) makes it
    appear in the TOC. Placing it AFTER the H1 — not before — also keeps
    the mobile TOC grouping intact, because the mobile TOC treats each
    article's H1 as a group header and bins subsequent H2/H3 underneath.

    Falls back to prepending if no H1 exists (defensive — should be rare
    because ``_normalize_article_headings`` guarantees one).
    """
    if not summary or not summary.strip():
        return article_text

    summary = summary.strip()
    block = f"### {label}\n\n{summary}\n"

    lines = article_text.split("\n")
    for i, line in enumerate(lines):
        # First H1 only (single '#' followed by space, NOT '##' or deeper)
        stripped = line.lstrip()
        if stripped.startswith('# ') and not stripped.startswith('## '):
            # Insert block right after this H1 line, with a blank line
            # buffer for clean markdown rendering
            head = "\n".join(lines[:i + 1])
            tail = "\n".join(lines[i + 1:])
            return f"{head}\n\n{block}\n{tail}" if tail else f"{head}\n\n{block}"

    # No H1 found — fallback: prepend so the summary is never lost
    return f"{block}\n{article_text}"


def _normalize_article_headings(article_text, fallback_title=None):
    """Guarantee exactly one H1 at the start of the article.

    The archive site's TOC assumes each article begins with an H1 (group
    header) followed by H2/H3 (children). Gemini's heading level varies
    between runs, so we normalize here instead of trusting the model.

    Rules:
      - First heading is promoted to H1 (even if Gemini used ##/###).
      - Any subsequent H1 is demoted to H2 (prevents mid-article TOC breaks).
      - Other heading levels are untouched.
      - Content inside fenced code blocks is left alone.
      - If the article has no heading at all and fallback_title is given,
        prepend "# {fallback_title}" so the article still appears in TOC.
    """
    parts = _FENCE_RE.split(article_text)
    seen_first = [False]  # list for closure mutability across inner calls

    def process(segment):
        lines = segment.split('\n')
        out = []
        for line in lines:
            m = _HEADING_RE.match(line)
            if not m:
                out.append(line)
                continue
            level = len(m.group(1))
            rest = m.group(2)
            if not seen_first[0]:
                out.append('#' + rest)  # promote to H1
                seen_first[0] = True
            else:
                new_level = max(level, 2)  # demote stray H1 to H2
                out.append('#' * new_level + rest)
        return '\n'.join(out)

    result = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # odd indices are fenced code blocks
            result.append(part)
        else:
            result.append(process(part))

    normalized = ''.join(result)
    if not seen_first[0] and fallback_title:
        normalized = f'# {fallback_title}\n\n' + normalized
    return normalized


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
        # Stash any unstaged changes so pull --rebase doesn't fail
        stash_result = subprocess.run(
            ["git", "stash"],
            cwd=str(repo_path), capture_output=True,
        )
        stashed = b"No local changes" not in stash_result.stdout
        try:
            subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=str(repo_path), check=True, capture_output=True,
            )
        finally:
            if stashed:
                subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=str(repo_path), capture_output=True,
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


def trigger_vercel_deploy():
    """Explicitly POST to the Vercel Deploy Hook to force a rebuild.

    Independent of the GitHub -> Vercel auto webhook, so a dropped or
    skipped webhook does not silently leave the site stale.
    """
    if not VERCEL_DEPLOY_HOOK_URL:
        return
    try:
        r = requests.post(VERCEL_DEPLOY_HOOK_URL, timeout=30)
        if r.ok:
            print("  [OK] Vercel deploy hook triggered")
        else:
            print(f"  [!] Vercel deploy hook returned HTTP {r.status_code}")
    except Exception as e:
        print(f"  [!] Vercel deploy hook failed: {e}")


def export_newsletter_issue(en_articles, ko_articles, audio_paths_en=None, audio_paths_ko=None, drill_sentences=None, frame_data=None):
    """
    Main entry point for archive export.
    1. Upload audio files to R2
    2. Upload captured frames to R2
    3. Generate issue markdown (with inline frame images)
    4. Push to archive repo

    frame_data: {seconds: (local_jpg_path, caption)} from capture_frames.
    """
    print("\n[STEP 4b] Exporting to archive...")

    # 1. Upload audio to R2
    audio_urls = []
    for paths in [audio_paths_en or [], audio_paths_ko or []]:
        for path in paths:
            url = upload_audio_to_r2(path)
            if url:
                audio_urls.append(url)

    # 2. Upload each article's captured frames to R2 and attach a per-article
    #    frame_map. Per-article (not global) avoids second-key collisions when
    #    two videos pick the same timestamp. Uploads are cached by local path
    #    so EN/KO sharing the same frames upload once.
    upload_cache = {}

    def _frame_map_for(article):
        fd = article.get("frame_data")  # {seconds: (local_path, caption)}
        if not fd:
            return None
        fmap = {}
        for seconds, (local_path, caption) in fd.items():
            if local_path not in upload_cache:
                upload_cache[local_path] = upload_image_to_r2(local_path)
            url = upload_cache[local_path]
            if url:
                fmap[seconds] = (url, caption)
        return fmap

    for art in list(en_articles or []) + list(ko_articles or []):
        fmap = _frame_map_for(art)
        if fmap:
            art["frame_map"] = fmap

    # Legacy/global path (tests, single-video callers without per-article data)
    legacy_frame_map = {}
    for seconds, (local_path, caption) in (frame_data or {}).items():
        url = upload_image_to_r2(local_path)
        if url:
            legacy_frame_map[seconds] = (url, caption)

    # 3. Generate issue markdown (frame markers -> inline images)
    filename, content = generate_issue_markdown(
        en_articles, ko_articles, audio_urls,
        drill_sentences=drill_sentences, frame_map=legacy_frame_map,
    )

    # 3. Push to archive repo
    pushed = push_to_archive_repo(content, filename)

    # 4. Explicitly trigger Vercel rebuild (belt-and-suspenders over GitHub auto webhook)
    if pushed:
        trigger_vercel_deploy()

    print("  [OK] Archive export complete\n")
