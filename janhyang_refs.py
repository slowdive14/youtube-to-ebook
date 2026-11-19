"""
Step 4c: hand the day's psychology articles to the 잔향 newsletter as drafting
material.

잔향 (a Korean psychology newsletter, its own project on the G: drive) turns
English psychology podcast episodes into Korean pieces, always from the full
transcript. Two of each day's articles here come from the same shows
(psych_sources.py), so for each of them two files go into 잔향's folder:

  output/raw/<name>.md        the episode's full transcript in 잔향's own raw
                              format (frontmatter + [mm:ss] paragraphs), so its
                              draft_piece.py / verify_piece.py take it as is.
                              Never overwrites a file 잔향 fetched itself
                              (podscripts.co text is better than recognition).
  output/blog_refs/<name>.md  the blog's Korean and English articles, episode
                              summary and per-section summaries with where
                              each section starts in the audio. Reference
                              only: AI-written, so 잔향's facts come from raw.

<name> follows 잔향's raw_path() (date_podcast-slug_title-slug), so both sides
name an episode the same way. The folder is JANHYANG_DIR (default below); when
it isn't there (Drive not mounted), the step is skipped.
"""

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = r"G:\내 드라이브\DriveSyncFiles\Learning Journey\3. Projects\3.2. 뉴스레터\뉴스레터 자동화"
SITE = "https://youtube-to-ebook-seven.vercel.app"
# A transcript paragraph covers about this much audio.
PARAGRAPH_SECONDS = 60


def janhyang_dir():
    return Path(os.getenv("JANHYANG_DIR", DEFAULT_DIR))


# --- the same naming as 잔향's jh_common.slugify / fetch_transcript.raw_path ---

def _slugify(text, maxlen):
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = "-".join(re.findall(r"[a-z0-9]+", folded.lower()))
    return slug[:maxlen].strip("-") or "untitled"


def file_name(podcast, title, published):
    return f"{published}_{_slugify(podcast, 24)}_{_slugify(title, 60)}.md"


def _fmt_time(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _frontmatter(meta):
    return "\n".join(["---", *(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()), "---", ""])


def paragraphs(segments, span=PARAGRAPH_SECONDS):
    """Sentences [{start, text}] -> "[mm:ss] ..." paragraphs of ~`span` seconds."""
    out, current, start = [], [], None
    for seg in segments:
        if current and seg["start"] - start >= span:
            out.append(f"[{_fmt_time(start)}] " + " ".join(current))
            current = []
        if not current:
            start = seg["start"]
        current.append(seg["text"])
    if current:
        out.append(f"[{_fmt_time(start)}] " + " ".join(current))
    return out


def raw_text(video, today):
    paras = paragraphs(video.get("transcript_segments") or [])
    words = sum(len(p.split()) - 1 for p in paras)
    published = video["published"][:10]
    meta = {
        "podcast": video["channel"],
        "title": video["title"],
        "published": published,
        "episode_url": video.get("url", ""),
        "transcript_source": "whisper",
        "transcript_url": video.get("audio_url", ""),
        # Machine recognition: names and terms may be misheard, like auto captions.
        "auto_captions": True,
        "words": words,
        "fetched": today,
    }
    return "\n".join([
        _frontmatter(meta),
        f"# {video['title']}",
        "",
        f"- 팟캐스트: {video['channel']}",
        f"- 공개일: {published}",
        f"- 에피소드 페이지: {video.get('url', '')}",
        f"- 원문 출처: whisper · {video.get('audio_url', '')}",
        f"- 분량: 약 {words:,}단어 (음성 인식, YouTube Digest가 생성)",
        "",
        "## 에피소드 소개 (RSS)",
        "",
        (video.get("description") or "").strip() or "(없음)",
        "",
        "## 트랜스크립트",
        "",
        "\n\n".join(paras),
        "",
    ])


def ref_text(en, ko, raw_name, issue_url, today):
    lines = [
        _frontmatter({
            "podcast": en["channel"],
            "title": en["title"],
            "published": en.get("published", "")[:10],
            "episode_url": en.get("url", ""),
            "blog_issue": issue_url,
            "raw_file": f"output/raw/{raw_name}",
            "category": en.get("category", ""),
            "created": today,
        }),
        f"# {en['title']}",
        "",
        "> YouTube Digest(테크 블로그)가 Gemini로 쓴 기사입니다. 꼭지 준비용 참고 자료이며, "
        f"사실 근거는 원문 `output/raw/{raw_name}`에서 확인하세요.",
        "",
    ]
    if ko and ko.get("summary"):
        lines += ["## 에피소드 요약", "", ko["summary"].strip(), ""]
    sums = (ko or {}).get("section_summaries") or {}
    if sums:
        times = (ko or {}).get("section_times") or {}
        lines += ["## 대목별 요약", ""]
        for heading, summary in sums.items():
            at = f"[{_fmt_time(times[heading])}] " if heading in times else ""
            lines.append(f"- {at}**{heading}**: {summary}")
        lines.append("")
    if ko:
        lines += ["## 한국어 기사", "", ko["article"].strip(), ""]
    lines += ["## English article", "", en["article"].strip(), ""]
    return "\n".join(lines)


def write_refs(en_articles, ko_articles, videos, folder=None, today=None):
    """Write raw + blog_refs files for the psychology articles. Returns paths written."""
    psych = [a for a in en_articles or [] if a.get("group") == "psych"]
    if not psych:
        return []
    base = Path(folder) if folder else janhyang_dir()
    if not base.exists():
        print(f"\n[STEP 4c] 잔향 folder not found ({base}); drafting material skipped")
        return []
    print(f"\n[STEP 4c] 잔향 drafting material for {len(psych)} psychology article(s)...")

    today = today or datetime.now().strftime("%Y-%m-%d")
    issue_url = f"{SITE}/issues/{today}"
    ko_by_id = {a.get("video_id"): a for a in ko_articles or []}
    video_by_id = {v.get("video_id"): v for v in videos or []}
    (base / "output" / "raw").mkdir(parents=True, exist_ok=True)
    (base / "output" / "blog_refs").mkdir(parents=True, exist_ok=True)

    written = []
    for en in psych:
        video = video_by_id.get(en.get("video_id"))
        if not video or not video.get("transcript_segments"):
            continue
        name = file_name(video["channel"], video["title"], video["published"][:10])
        raw = base / "output" / "raw" / name
        if raw.exists():
            print(f"  [.] 잔향 already has the transcript: {name}")
        else:
            raw.write_text(raw_text(video, today), encoding="utf-8")
            written.append(raw)
        ref = base / "output" / "blog_refs" / name
        ref.write_text(ref_text(en, ko_by_id.get(en.get("video_id")), name, issue_url, today), encoding="utf-8")
        written.append(ref)
        print(f"  [OK] {name}")
    return written
