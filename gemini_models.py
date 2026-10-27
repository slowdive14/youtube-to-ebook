"""
Which Gemini model answers a request, and what happens when one can't.

Free-tier quota is counted per model (Flash models get ~20 requests a day
each), so a request whose model has run out moves on to the next model in the
chain instead of failing the day's digest. Every pipeline call goes through
generate() here.

Measured on this project's free key on 2026-10-27:
- Every model in DEFAULT_CHAIN answers. "Free keys only get Flash-Lite" is
  not true for this key, but Flash is slow on it: one article took 152 s on
  3.8 Flash against 6.7 s on 3.5 Flash-Lite.
- Lite writes much less. The same article came out at 961 words on 3.5
  Flash-Lite, 1,550 on 3.8 Flash and 1,710 on 2.5 Flash. The pipeline is a
  morning batch nobody waits on, so it starts at the newest Flash and keeps
  Lite as the last resort. The site's routes, where a learner is waiting,
  start at Flash-Lite instead (youtube-digest-archive/src/lib/gemini.ts).
- 3.5 Flash-Lite refuses thinking_budget=0 with a 400. Gemini 3 models take
  thinking_level="minimal" instead, so `fast` requests are given whichever
  setting their model accepts.
"""

import os
import re

from google.genai import types

DEFAULT_CHAIN = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",       # served only to keys that used 2.5 before (this one did)
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
)

# A free-key Flash answer has taken 152 s; past this the model is treated as
# stuck and the next one is asked. GEMINI_TIMEOUT in .env overrides it.
DEFAULT_TIMEOUT = 300

# Overload or a per-minute limit moves a request to the next model this many
# times at most; then the error goes back to the caller, whose own backoff
# retries later. Overload retries count against the daily quota too, so an
# outage must not run every model in the chain dry.
MAX_BUSY_HOPS = 2

# model -> why it is skipped for the rest of this run
_skipped = {}


class NoModelLeft(RuntimeError):
    """Every model in the chain is used up for today, not offered, or stuck.

    Callers don't retry this: nothing will change until the quotas reset.
    """


def reset():
    """Forget skipped models (tests; a long-lived process after the reset)."""
    _skipped.clear()


def skipped():
    return dict(_skipped)


def model_chain():
    """DEFAULT_CHAIN, or GEMINI_MODELS="a,b,c" from .env when Google ships or
    retires a model. Read per call, so it works whatever loaded .env first."""
    custom = tuple(m.strip() for m in os.getenv("GEMINI_MODELS", "").split(",") if m.strip())
    return custom or DEFAULT_CHAIN


def chain(first=None):
    """The order models are asked in.

    With `first`, the chain starts there and carries on down, coming back to
    the models above it only at the end — so a backfill started lower down
    uses the newest model last, leaving it to the morning run. A `first`
    outside the chain is asked before the whole chain.
    """
    models = list(model_chain())
    if not first:
        return models
    if first in models:
        i = models.index(first)
        return models[i:] + models[:i]
    return [first] + models


def fast_thinking(model):
    """The least thinking `model` accepts: Gemini 2.5 takes a zero budget,
    Gemini 3 refuses that (3.5 Flash-Lite with a 400) and takes a level."""
    if model.startswith("gemini-2."):
        return types.ThinkingConfig(thinking_budget=0)
    return types.ThinkingConfig(thinking_level="minimal")


def config_for(model, config, fast=False, timeout=None):
    update = {}
    if fast:
        update["thinking_config"] = fast_thinking(model)
    if timeout:
        update["http_options"] = types.HttpOptions(timeout=int(timeout * 1000))
    if config is None:
        return types.GenerateContentConfig(**update)
    return config.model_copy(update=update) if update else config


def classify_error(error):
    """What a failed call means for the chain.

    daily  - this model's quota for today is spent: skip it for the run
    gone   - this model isn't offered to this key: skip it for the run
    slow   - no answer within the timeout: skip it for the run
    busy   - overloaded or a per-minute limit: ask the next model this time
    fatal  - the request itself is at fault: raise it as is
    """
    text = str(error)
    low = text.lower()
    code = getattr(error, "code", None)
    if not isinstance(code, int):
        m = re.match(r"\s*(\d{3})\b", text)
        code = int(m.group(1)) if m else None

    if code == 429 or "resource_exhausted" in low:
        return "daily" if "PerDay" in text else "busy"
    if code in (403, 404) or "not_found" in low or "permission_denied" in low:
        return "gone"
    if code in (500, 502, 503, 504) or "unavailable" in low or "overloaded" in low:
        return "busy"
    if "timed out" in low or "timeout" in low:
        return "slow"
    return "fatal"


_REASONS = {
    "daily": "out of requests for today",
    "gone": "not offered to this key",
    "slow": "gave no answer in time",
}


def generate(client, contents, config=None, *, first=None, fast=False, timeout=None):
    """client.models.generate_content, moving down the chain when a model can't answer.

    first    model to start the chain at (see chain(); backfills start lower
             down so they leave the newest model's quota to the morning run)
    fast     ask for the least thinking the model accepts — for short
             extraction-style answers where thinking only eats max_output_tokens
    timeout  seconds before a model is treated as stuck (default
             GEMINI_TIMEOUT or DEFAULT_TIMEOUT)
    """
    timeout = timeout or int(os.getenv("GEMINI_TIMEOUT", DEFAULT_TIMEOUT))
    models = chain(first)
    busy_hops = 0
    last = None
    for model in models:
        if model in _skipped:
            continue
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config_for(model, config, fast=fast, timeout=timeout),
            )
        except Exception as e:  # noqa: BLE001 — sorted by classify_error
            kind = classify_error(e)
            if kind == "fatal":
                raise
            last = e
            if kind in _REASONS:
                _skipped[model] = _REASONS[kind]
                print(f"  [model] {model} {_REASONS[kind]}; trying the next model")
                continue
            busy_hops += 1
            if busy_hops > MAX_BUSY_HOPS:
                raise
            print(f"  [model] {model} busy ({str(e)[:50]}); trying the next model")
            continue

        if model != models[0]:
            print(f"  [model] answered by {model}")
        return response

    if all(m in _skipped for m in models):
        left = "; ".join(f"{m}: {_skipped[m]}" for m in models)
        raise NoModelLeft(f"No Gemini model can answer right now ({left})")
    raise last
