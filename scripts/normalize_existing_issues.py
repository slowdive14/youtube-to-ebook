"""One-off backfill: normalize heading levels in existing issue markdown files.

Background: Issues generated before the pipeline fix in export_archive.py have
inconsistent article heading levels (some articles start at H1, some at H2),
which breaks the archive site's TOC grouping. This script applies the same
`_normalize_article_headings` helper to each article inside each existing
issue file so their TOC renders correctly.

Safe to re-run: already-correct files produce no changes (the helper is a
no-op on articles that already begin with H1 and have no stray H1 later).
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from export_archive import _normalize_article_headings

ISSUES_DIR = REPO_ROOT / "youtube-digest-archive" / "src" / "content" / "issues"

# A real article/language separator is a "---" line whose *next* meaningful
# content is one of the known pipeline-generated headers:
#   - "## English" / "## 한국어" — language divider
#   - "> Based on **\"" — English article blockquote header
#   - "> **\"TITLE\"** — **CHANNEL** 기반 기사" — Korean article blockquote header
# Any other "---" (e.g., one Gemini writes inside an article as a horizontal
# rule between sub-sections) must NOT be treated as a split point — otherwise
# the first heading of the next chunk (often "### Section") gets promoted to
# "# Section" and the article's internal hierarchy collapses.
_REAL_SEP_RE = re.compile(
    r'\n---\n'
    r'(?=\s*(?:## (?:English|한국어)\b'
    r'|> Based on \*\*"'
    r'|> \*\*"[^\n]*\*\* — \*\*[^\n]*\*\* 기반 기사))'
)


def _split_frontmatter(text):
    """Return (frontmatter_block, body) splitting on the closing --- fence.

    Frontmatter must start at the very first line with ---. If no valid
    frontmatter is found, returns ('', text).
    """
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    fm = text[: end + len("\n---\n")]
    return fm, text[end + len("\n---\n") :]


def _normalize_segment(segment):
    """A segment is "<optional lang divider + blockquote>\\n\\n<gemini article>".

    Keep the prefix up to the end of the *first* blockquote block (the article
    header that the pipeline emits), then normalize only the article body that
    follows. Using the first blockquote block — not the last — matters because
    some articles end with a blockquoted exercise/takeaway section; picking
    the last blockquote would swallow the real article body into the prefix
    and skip heading normalization entirely.
    """
    lines = segment.split("\n")

    # Skip leading blanks and language-divider lines ("## English" / "## 한국어").
    i = 0
    while i < len(lines) and (
        lines[i].strip() == "" or lines[i].startswith("## ")
    ):
        i += 1

    # If no blockquote header starts here, treat whole segment as body.
    if i >= len(lines) or not lines[i].startswith("> "):
        return _normalize_article_headings(segment)

    # Consume the consecutive "> " lines that form the article header.
    while i < len(lines) and lines[i].startswith("> "):
        i += 1
    body_start = i

    # If there's nothing after the header, leave segment untouched (avoids
    # appending spurious trailing newlines on re-runs).
    if body_start >= len(lines):
        return segment

    prefix = "\n".join(lines[:body_start])
    body = "\n".join(lines[body_start:])
    normalized_body = _normalize_article_headings(body)

    return prefix + "\n" + normalized_body


def normalize_file(path):
    """Normalize headings in one issue file. Returns True if content changed."""
    original = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(original)

    segments = _REAL_SEP_RE.split(body)
    new_segments = [_normalize_segment(s) for s in segments]
    new_body = "\n---\n".join(new_segments)
    new_content = fm + new_body

    if new_content == original:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def main():
    changed = 0
    total = 0
    for path in sorted(ISSUES_DIR.glob("*.md")):
        total += 1
        if normalize_file(path):
            changed += 1
            print(f"  [MODIFIED] {path.name}")
        else:
            print(f"  [unchanged] {path.name}")
    print(f"\n{changed}/{total} files modified")


if __name__ == "__main__":
    main()
