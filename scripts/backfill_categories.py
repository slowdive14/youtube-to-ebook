"""Backfill: give every archived article a category (its subject area).

New articles get theirs from the pipeline: Step 1c/1d label each video with a
subject area (select_videos.DOMAINS) and export_archive writes it to the
article's frontmatter as `category`. Issues made before that have none, so
this labels them the same way, from each article's title, channel and the
opening of its episode summary.

Many articles go in one request (--batch, default 80), so the whole archive
of ~430 articles is about 6 requests. Runs on gemini-3.5-flash by default, NOT
the pipeline's gemini-2.5-flash: free-tier quotas are per model (20/day) and
the morning run spends ~15 of 2.5-flash's.

Only `category:` lines are added; nothing else in the file changes. Articles
that already have one are left alone unless --force. An article the model
doesn't label is left without one (no keyword guess written in for good) —
re-run to fill it.

    py scripts/backfill_categories.py --dry-run
    py scripts/backfill_categories.py
    py scripts/backfill_categories.py --issue 2026-10-02 --force
"""

import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import collections
import re
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from select_videos import classify_videos, DOMAINS
from scripts.normalize_existing_issues import _split_frontmatter

ISSUES_DIR = REPO_ROOT / "youtube-digest-archive" / "src" / "content" / "issues"

_ENTRY_RE = re.compile(r'^  - title: ')
_URL_RE = re.compile(r'^    url: ')
_CATEGORY_RE = re.compile(r'^    category: ')


def set_categories(frontmatter, categories):
    """Write `category:` into article entries of a frontmatter block.

    `categories` maps the article's position in `articles:` to a domain. The
    line goes right after that entry's `url:` (replacing an existing
    `category:` line). Everything else is returned byte for byte.
    """
    out = []
    in_articles = False
    index = -1
    new = None  # category for the current entry, if it gets one

    for line in frontmatter.split("\n"):
        if line == "articles:":
            in_articles = True
        elif in_articles and line and not line.startswith(" "):
            in_articles = False  # next top-level key

        if in_articles and _ENTRY_RE.match(line):
            index += 1
            new = categories.get(index)
        elif in_articles and new and _CATEGORY_RE.match(line):
            continue  # the old line goes, wherever it sat in the entry

        out.append(line)

        if in_articles and new and _URL_RE.match(line):
            out.append(f'    category: "{new}"')

    return "\n".join(out)


def load_articles(path):
    """[(index, article_dict)] from an issue's frontmatter."""
    fm, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    if not fm:
        return []
    data = yaml.safe_load(fm.strip().strip("-")) or {}
    return list(enumerate(data.get("articles") or []))


def classify_with_retry(videos, model, attempts=3):
    """classify_videos without the keyword fallback, retried on a total miss.

    A total miss is an API error (503 overload, mostly); a partial result is
    kept as is and the gaps are left for the next run.
    """
    for attempt in range(attempts):
        labels = [d for _, d in classify_videos(videos, model=model, fallback=False)]
        if any(labels):
            return labels
        if attempt < attempts - 1:
            wait = 15 * (attempt + 1)
            print(f"  [.] No labels back; retrying in {wait}s...")
            time.sleep(wait)
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issue", help="one issue id, e.g. 2026-10-02")
    parser.add_argument("--batch", type=int, default=80, help="articles per request")
    parser.add_argument("--delay", type=float, default=5.0, help="seconds between requests")
    parser.add_argument("--force", action="store_true", help="relabel articles that have a category")
    parser.add_argument("--model", default="gemini-3.5-flash",
                        help="Gemini model (default keeps off the pipeline's 2.5-flash quota)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    paths = [ISSUES_DIR / f"{args.issue}.md"] if args.issue else sorted(ISSUES_DIR.glob("*.md"))

    # (path, index, article) for every article that needs a label
    todo = []
    for path in paths:
        if not path.exists():
            print(f"  [!] {path.name} not found")
            continue
        for index, article in load_articles(path):
            if article.get("category") and not args.force:
                continue
            todo.append((path, index, article))

    print(f"{len(todo)} article(s) to label, {args.batch} per request "
          f"(~{-(-len(todo) // args.batch) if todo else 0} requests on {args.model})")
    if not todo:
        return

    found = {}  # (path, index) -> domain
    for start in range(0, len(todo), args.batch):
        chunk = todo[start:start + args.batch]
        if start and args.delay:
            time.sleep(args.delay)
        videos = [
            {"title": a.get("title", ""), "channel": a.get("channel", ""), "summary": a.get("summary", "")}
            for _, _, a in chunk
        ]
        labels = classify_with_retry(videos, args.model)
        got = sum(1 for d in labels if d)
        print(f"  [{start + 1}-{start + len(chunk)}] {got}/{len(chunk)} labelled")
        for (path, index, _), domain in zip(chunk, labels):
            if domain:
                found[(path, index)] = domain

    by_path = collections.defaultdict(dict)
    for (path, index), domain in found.items():
        by_path[path][index] = domain

    counts = collections.Counter(found.values())
    print("\n" + "  ".join(f"{d} {counts[d]}" for d in DOMAINS if counts[d]))
    missing = len(todo) - len(found)
    if missing:
        print(f"{missing} left unlabelled — re-run to fill them")

    if args.dry_run:
        for (path, index, article) in todo:
            domain = found.get((path, index), "-")
            print(f"  {domain:11} {path.stem}  {article.get('title', '')[:60]}")
        print("\n[DRY] nothing written")
        return

    for path, categories in sorted(by_path.items()):
        text = path.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(text)
        path.write_text(set_categories(fm, categories) + body, encoding="utf-8")
    print(f"\nWrote {len(found)} categories into {len(by_path)} issue(s).")


if __name__ == "__main__":
    main()
