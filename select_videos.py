"""
Step 1c: Curate the day's videos down to a handful, spread across subjects.

The channel list produces 6-9 new videos a day. That's more reading than
anyone gets through, and on a free-tier API key each video costs ~6 requests.
So we keep only a few — chosen so they don't all cover the same ground.

Selection is by DOMAIN SPREAD, not by topic preference: one video per subject
area, so a day reads as technology + health + culture rather than three takes
on the same news cycle. Classification is one Gemini call on titles alone,
before transcripts are fetched, so a dropped video costs nothing beyond that
call. If it fails we fall back to a keyword heuristic rather than dropping the
digest.
"""

import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import json
import os
import re

DEFAULT_LIMIT = int(os.getenv("MAX_ARTICLES_PER_DAY", "3"))

# Buckets are deliberately coarse. Finer ones (AI vs software, elections vs
# war) would split near-identical videos into "different" domains and defeat
# the whole point of the spread.
DOMAINS = ("technology", "science", "health", "business", "politics", "culture", "other")

CLASSIFY_PROMPT = """Label each video with the ONE subject area that fits it best.

Use exactly one of these labels:
- technology: AI, software, computing, robotics, chips, the tech industry
- science: physics, maths, space, biology, nature, research
- health: medicine, nutrition, fitness, psychology, mental health
- business: economics, markets, companies, money, work
- politics: elections, government, policy, war, international relations
- culture: media, art, music, history, society, education, religion
- other: anything that genuinely fits none of the above

Judge the actual subject, not the channel's usual beat: a politics channel
covering chip export controls is technology; a tech channel covering an
election is politics.

VIDEOS:
{listing}

Reply with JSON only, one entry per video, same indexes:
{{"videos": [{{"index": 0, "domain": "technology"}}]}}"""


# Fallback only — a rough keyword map used when the API call fails.
_DOMAIN_KEYWORDS = [
    ("technology", r"\b(ai|a\.i\.|artificial intelligence|llm|gpt|chatgpt|claude|gemini|"
                   r"machine learning|neural|openai|anthropic|robot|semiconductor|chip|gpu|"
                   r"software|computer|computing|algorithm|startup|silicon valley|internet|app)\b"),
    ("science", r"\b(physics|quantum|math|mathematics|space|nasa|rocket|satellite|astronom|"
                r"biology|evolution|climate|ocean|geolog|chemistry|scientist|experiment)\b"),
    ("health", r"\b(health|medicine|medical|doctor|disease|cancer|brain|sleep|diet|"
               r"nutrition|exercise|fitness|therapy|depression|anxiety|mental|gut|body)\b"),
    ("business", r"\b(econom|market|stock|inflation|recession|tariff|trade|money|oil|"
                 r"business|company|ceo|industry|price|invest|wealth|labor|job)\b"),
    ("politics", r"\b(war|election|president|senate|congress|geopolitic|diplomat|sanction|"
                 r"military|government|policy|law|court|immigration|protest|vote)\b"),
    ("culture", r"\b(music|film|movie|art|book|history|religion|philosoph|culture|media|"
                r"hollywood|school|education|language|family|community|social)\b"),
]


def _heuristic_domain(video):
    """Keyword-based domain guess. Used only when Gemini is unavailable."""
    text = f"{video.get('title', '')} {video.get('channel', '')}".lower()
    for domain, pattern in _DOMAIN_KEYWORDS:
        if re.search(pattern, text):
            return domain
    return "other"


def parse_domains(text, count):
    """Parse the model's JSON into {index: domain}.

    Unknown labels and out-of-range indexes are dropped so a hallucinated row
    can't knock the classification out of alignment with the video list.
    """
    if not text or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}

    items = data.get("videos") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}

    out = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        domain = str(item.get("domain", "")).strip().lower()
        if 0 <= idx < count and domain in DOMAINS:
            out[idx] = domain
    return out


def classify_videos(videos):
    """Label every video with a subject area.

    Returns [(video, domain)] in the input order, falling back to the keyword
    heuristic for any video the model didn't label.
    """
    if not videos:
        return []

    listing = "\n".join(
        f'{i}. "{v.get("title", "")}" — {v.get("channel", "")}'
        for i, v in enumerate(videos)
    )

    labels = {}
    try:
        from google.genai import types
        from write_articles import client, _log_usage_metadata

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=CLASSIFY_PROMPT.format(listing=listing),
            config=types.GenerateContentConfig(
                max_output_tokens=1000,
                temperature=0.1,
                response_mime_type='application/json',
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        _log_usage_metadata(response, label='Video-classify')
        labels = parse_domains(response.text or "", len(videos))
    except Exception as e:
        print(f"  [!] Domain classification failed ({e}); using keyword fallback")

    return [(v, labels.get(i) or _heuristic_domain(v)) for i, v in enumerate(videos)]


def select_diverse_videos(videos, limit=None):
    """Keep up to `limit` videos, each from a different subject area.

    Takes the first video of each domain in the order the channel list gave
    them, so the pick is deterministic. Only once every domain present is
    represented does it start allowing a second from the same one — that way
    a day with three technology videos and nothing else still fills up, but a
    day with a real spread always shows the spread first.
    """
    limit = DEFAULT_LIMIT if limit is None else limit
    if not videos or limit <= 0:
        return list(videos)
    if len(videos) <= limit:
        return list(videos)

    classified = classify_videos(videos)

    kept = []
    used_domains = set()
    leftovers = []
    for video, domain in classified:
        if len(kept) < limit and domain not in used_domains:
            kept.append((video, domain))
            used_domains.add(domain)
        else:
            leftovers.append((video, domain))

    # Not enough distinct domains to fill the quota — top up in order.
    for video, domain in leftovers:
        if len(kept) >= limit:
            break
        kept.append((video, domain))

    kept_ids = {id(v) for v, _ in kept}
    print(f"\n  Picked {len(kept)} of {len(videos)} videos across subject areas:")
    for video, domain in classified:
        mark = "  [KEEP]" if id(video) in kept_ids else "  [skip]"
        print(f"{mark} {domain:11} {video.get('title', '')[:52]}")

    return [v for v, _ in kept]
