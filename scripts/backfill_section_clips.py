"""Backfill: add "원본 영상 MM:SS" clips to the sections of existing issues.

New issues get these from the pipeline: the section-summary request carries
the timed transcript and returns each section's start time alongside its
summary (write_articles.generate_section_guide). Older issues were made before
that, and the pipeline doesn't keep transcripts, so this re-fetches each
video's transcript and regenerates that article's section summaries + times
in the same single request. Existing [[SUM]] lines are replaced.

One Gemini request per article per language (same as the summary backfill)
plus one free transcript fetch per video, shared by its EN and KO halves.

    py scripts/backfill_section_clips.py --issue 2026-10-02
    py scripts/backfill_section_clips.py --limit 3
    py scripts/backfill_section_clips.py --limit 3 --dry-run
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
    extract_section_headings,
    generate_section_guide,
    inject_section_summaries,
)
from export_archive import youtube_video_id
from get_transcripts import get_transcript
from scripts.normalize_existing_issues import _REAL_SEP_RE, _split_frontmatter
from scripts.backfill_section_summaries import _segment_language

ISSUES_DIR = REPO_ROOT / "youtube-digest-archive" / "src" / "content" / "issues"

_VIDEO_LINK_RE = re.compile(r'\((https://(?:www\.)?youtube\.com/watch\?v=[\w-]{11}[^)]*)\)')
_OLD_MARKER_RE = re.compile(r'^\[\[(?:SUM\]\].*|AT:[\w-]{11}:\d+\]\])\n?', re.MULTILINE)


def _strip_markers(segment):
    """Remove existing [[SUM]] / [[AT:..]] lines so they can be regenerated."""
    return re.sub(r'\n{3,}', '\n\n', _OLD_MARKER_RE.sub('', segment))


def backfill_file(path, delay, dry_run=False, force=False):
    """Add clip markers to one issue. Returns the number of clips written."""
    original = path.read_text(encoding="utf-8")
    if "[[AT:" in original and not force:
        print(f"  [SKIP] {path.name} (already has clips)")
        return 0

    fm, body = _split_frontmatter(original)
    segments = _REAL_SEP_RE.split(body)

    transcripts = {}  # video_id -> timed segments, shared by EN and KO halves
    clips = 0
    calls = 0
    out = []
    language = 'en'

    for segment in segments:
        language = _segment_language(segment, language)
        link = _VIDEO_LINK_RE.search(segment)
        vid = youtube_video_id(link.group(1)) if link else None
        clean = _strip_markers(segment)

        if not vid or not extract_section_headings(clean):
            out.append(segment)
            continue

        if vid not in transcripts:
            _, timed = get_transcript(vid)
            transcripts[vid] = timed
        timed = transcripts[vid]
        if not timed:
            print(f"    [{language}] {vid}: no transcript — left as is")
            out.append(segment)
            continue

        if calls and delay:
            time.sleep(delay)
        calls += 1

        sums, times = generate_section_guide(clean, language=language, is_first=True, segments=timed)
        if not sums:
            print(f"    [{language}] {vid}: generation failed — left as is")
            out.append(segment)
            continue

        out.append(inject_section_summaries(clean, sums, times=times, video_id=vid))
        clips += len(times)
        print(f"    [{language}] {vid}: {len(sums)} summaries, {len(times)} clips")

    if not clips:
        print(f"  [--] {path.name}: no clips")
        return 0

    new_content = fm + "\n---\n".join(out)
    if dry_run:
        print(f"  [DRY] {path.name}: would write {clips} clips")
        return clips
    path.write_text(new_content, encoding="utf-8")
    print(f"  [OK] {path.name}: {clips} clips")
    return clips


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", help="one issue id, e.g. 2026-10-02")
    parser.add_argument("--limit", type=int, default=0, help="only the N newest issues")
    parser.add_argument("--delay", type=float, default=4.0, help="seconds between API calls")
    parser.add_argument("--force", action="store_true", help="redo issues that already have clips")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.issue:
        paths = [ISSUES_DIR / f"{args.issue}.md"]
    else:
        paths = sorted(ISSUES_DIR.glob("*.md"), reverse=True)
        if args.limit:
            paths = paths[: args.limit]

    total = 0
    for i, path in enumerate(paths):
        if not path.exists():
            print(f"  [!] {path.name} not found")
            continue
        print(f"\n[{i + 1}/{len(paths)}] {path.name}")
        try:
            total += backfill_file(path, args.delay, dry_run=args.dry_run, force=args.force)
        except KeyboardInterrupt:
            print("\nInterrupted — finished files are already written. Re-run to continue.")
            break
        except Exception as e:
            print(f"  [!] {path.name} failed: {e}")

    print(f"\nDone. {total} clips written.")


if __name__ == "__main__":
    main()
