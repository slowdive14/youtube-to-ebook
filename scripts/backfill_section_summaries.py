"""Backfill: add per-section `[[SUM]]` summary lines to existing issue files.

New issues get these from the pipeline (write_articles.generate_section_summaries
-> export_archive._render_article_body). Issues published before that existed
have no markers, so the archive site falls back to showing each section's first
paragraph as the summary line. This script fills in the real AI summaries.

One Gemini call per article. Resumable and safe to re-run: files that already
contain markers are skipped, and each file is written as soon as it's done, so
an interrupted run keeps everything it finished.

    py scripts/backfill_section_summaries.py --limit 5     # newest 5 issues
    py scripts/backfill_section_summaries.py --dry-run
    py scripts/backfill_section_summaries.py               # everything left
"""

import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import re
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from write_articles import (
    SECTION_SUMMARY_MARKER,
    extract_section_headings,
    generate_section_summaries,
    inject_section_summaries,
)
from scripts.normalize_existing_issues import _REAL_SEP_RE, _split_frontmatter

ISSUES_DIR = REPO_ROOT / "youtube-digest-archive" / "src" / "content" / "issues"


def _segment_language(segment, current):
    """Track which language half of the issue a segment belongs to."""
    if re.search(r'^## 한국어\s*$', segment, re.MULTILINE):
        return 'ko'
    if re.search(r'^## English\s*$', segment, re.MULTILINE):
        return 'en'
    return current


def backfill_file(path, delay, dry_run=False):
    """Add summary markers to one issue file. Returns the number of sections filled."""
    original = path.read_text(encoding="utf-8")
    if SECTION_SUMMARY_MARKER in original:
        print(f"  [SKIP] {path.name} (already has summaries)")
        return 0

    fm, body = _split_frontmatter(original)
    segments = _REAL_SEP_RE.split(body)

    filled = 0
    new_segments = []
    language = 'en'
    first_call = True

    for segment in segments:
        language = _segment_language(segment, language)
        headings = extract_section_headings(segment)
        if not headings:
            new_segments.append(segment)
            continue

        summaries = generate_section_summaries(
            segment, language=language, is_first=True  # pacing handled below
        )
        if summaries:
            new_segments.append(inject_section_summaries(segment, summaries))
            filled += len(summaries)
            print(f"    [{language}] {len(summaries)}/{len(headings)} sections")
        else:
            new_segments.append(segment)
            print(f"    [{language}] 0/{len(headings)} sections (failed)")

        if not first_call and delay:
            time.sleep(delay)
        first_call = False

    if not filled:
        print(f"  [--] {path.name}: nothing filled")
        return 0

    new_content = fm + "\n---\n".join(new_segments)
    if dry_run:
        print(f"  [DRY] {path.name}: would fill {filled} sections")
        return filled

    path.write_text(new_content, encoding="utf-8")
    print(f"  [OK] {path.name}: {filled} sections")
    return filled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="only the N newest issues")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between API calls")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Newest first — those are the issues actually being read.
    paths = sorted(ISSUES_DIR.glob("*.md"), reverse=True)
    pending = [p for p in paths if SECTION_SUMMARY_MARKER not in p.read_text(encoding="utf-8")]
    print(f"{len(pending)} of {len(paths)} issues still need summaries")

    if args.limit:
        pending = pending[: args.limit]

    total = 0
    for i, path in enumerate(pending):
        print(f"\n[{i + 1}/{len(pending)}] {path.name}")
        try:
            total += backfill_file(path, args.delay, dry_run=args.dry_run)
        except KeyboardInterrupt:
            print("\nInterrupted — finished files are already written. Re-run to continue.")
            break
        except Exception as e:
            print(f"  [!] {path.name} failed: {e}")

    print(f"\nDone. {total} section summaries written.")


if __name__ == "__main__":
    main()
