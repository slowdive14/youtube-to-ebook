"""
Step 1c: Curate the day's videos down to a handful, tech-first.

The channel list produces 6-9 new videos a day across tech, geopolitics,
economics and culture. That's more reading than anyone gets through, and on a
free-tier API key each video costs ~6 requests. So we score the day's titles
for technology relevance and keep only the top few.

Scoring is one Gemini call on titles alone — before transcripts are fetched,
so discarded videos cost nothing beyond that call. If it fails we fall back to
a keyword heuristic rather than dropping the digest.
"""

import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import json
import os
import re

DEFAULT_LIMIT = int(os.getenv("MAX_ARTICLES_PER_DAY", "4"))

# Below this score a video isn't worth a slot. 40 is the science/culture line
# in the rubric below: science and technology clear it, culture, politics and
# macroeconomics don't. Without a floor a quiet tech day silently backfills
# the digest with whatever scored least badly.
MIN_SCORE = float(os.getenv("MIN_TOPIC_SCORE", "40"))

SELECTION_PROMPT = """Score each video for how much it is about TECHNOLOGY.

The reader wants a technology digest — AI above all — and specifically does
NOT want their day filled with geopolitics, war, elections, or macroeconomics.

Score 0-100:
- 90-100: AI/machine learning, LLMs, AI research or industry
- 70-89: software, computing, robotics, semiconductors, space tech, engineering,
  biotech as technology, the tech industry itself
- 40-69: general science, mathematics, psychology, medicine, health research
- 10-39: culture, media, history, society, education
- 0-9: geopolitics, war, elections, national politics, macroeconomics, markets

Judge the actual subject, not the channel's usual beat: a politics channel
covering chip export controls scores high, a tech channel covering an election
scores low.

VIDEOS:
{listing}

Reply with JSON only, one entry per video, same indexes:
{{"scores": [{{"index": 0, "score": 0, "why": "<5 words>"}}]}}"""


# Fallback only — a rough keyword prior used when the API call fails.
_KEYWORD_SCORES = [
    (95, r"\b(ai|a\.i\.|artificial intelligence|llm|gpt|chatgpt|claude|gemini|"
         r"machine learning|neural|openai|anthropic|deepmind|agentic|transformer)\b"),
    (80, r"\b(robot|robotics|semiconductor|chip|gpu|quantum|software|computing|"
         r"computer|algorithm|startup|silicon valley|space ?x|satellite|rocket|"
         r"engineer|engineering|programming|code|coding|data cent(er|re))\b"),
    (55, r"\b(science|scientist|physics|math|mathematics|biology|neuroscience|"
         r"genetic|research|study|brain|medicine|medical|health)\b"),
    (5, r"\b(war|election|president|senate|congress|geopolitic|diplomat|tariff|"
        r"inflation|recession|economy|economic|market|oil|sanction|military)\b"),
]


def _heuristic_score(video):
    """Keyword prior on the title (0-100). Used only when Gemini is unavailable."""
    text = f"{video.get('title', '')} {video.get('channel', '')}".lower()
    for score, pattern in _KEYWORD_SCORES:
        if re.search(pattern, text):
            return score
    return 30  # unknown topic — below science, above politics


def parse_scores(text, count):
    """Parse the model's JSON into {index: (score, why)}.

    Ignores entries with an out-of-range index so a hallucinated row can't
    knock the ranking out of alignment with the video list.
    """
    if not text or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}

    items = data.get("scores") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}

    out = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < count:
            out[idx] = (score, str(item.get("why", "")).strip())
    return out


def score_videos(videos):
    """Score every video 0-100 for technology relevance.

    Returns [(video, score, why)] in the input order. Falls back to the
    keyword heuristic for any video the model didn't score.
    """
    if not videos:
        return []

    listing = "\n".join(
        f'{i}. "{v.get("title", "")}" — {v.get("channel", "")}'
        for i, v in enumerate(videos)
    )

    scores = {}
    try:
        from google.genai import types
        from write_articles import client, _log_usage_metadata

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=SELECTION_PROMPT.format(listing=listing),
            config=types.GenerateContentConfig(
                max_output_tokens=1500,
                temperature=0.2,
                response_mime_type='application/json',
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        _log_usage_metadata(response, label='Video-select')
        scores = parse_scores(response.text or "", len(videos))
    except Exception as e:
        print(f"  [!] Topic scoring failed ({e}); using keyword fallback")

    result = []
    for i, v in enumerate(videos):
        if i in scores:
            score, why = scores[i]
        else:
            score, why = _heuristic_score(v), "keyword fallback"
        result.append((v, score, why))
    return result


def select_tech_videos(videos, limit=None, min_score=None):
    """Keep up to `limit` technology-focused videos, best first.

    Two gates, not one: the cap AND a relevance floor. A cap alone backfills
    the digest on a quiet tech day — the day this was written, one video scored
    95 and the 4th-best was a culture piece at 15, which is exactly what the
    floor is there to drop.

    Always keeps at least one video, though: an empty digest also empties the
    speaking prompt and Velora's reading feed, which is worse than one
    off-topic article. Ties break toward the earlier video for determinism.
    """
    limit = DEFAULT_LIMIT if limit is None else limit
    min_score = MIN_SCORE if min_score is None else min_score
    if not videos or limit <= 0:
        return list(videos)
    if len(videos) == 1:
        return list(videos)

    scored = score_videos(videos)
    ranked = sorted(enumerate(scored), key=lambda p: (-p[1][1], p[0]))

    kept = [v for _, (v, score, _) in ranked[:limit] if score >= min_score]
    if not kept:
        kept = [ranked[0][1][0]]

    kept_ids = {id(v) for v in kept}
    print(f"\n  Ranked {len(videos)} videos by technology focus "
          f"(max {limit}, floor {min_score:g}):")
    for _, (v, score, why) in ranked:
        mark = "  [KEEP]" if id(v) in kept_ids else "  [skip]"
        reason = f" — {why}" if why else ""
        print(f"{mark} {score:5.1f}  {v.get('title', '')[:52]}{reason}")

    return kept
