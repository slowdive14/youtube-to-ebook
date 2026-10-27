"""
Tests for the Gemini model chain (gemini_models.py).

Free-tier quota is per model, so a request whose model has run out must move
on to the next one instead of failing the digest — and must not keep asking a
spent model, because every refused request still costs time and, during an
overload, quota.
"""

from types import SimpleNamespace

import pytest
from google.genai import types

import gemini_models
from gemini_models import (
    DEFAULT_CHAIN,
    NoModelLeft,
    chain,
    classify_error,
    config_for,
    fast_thinking,
    generate,
)

DAILY = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': "
         "[{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '20'}]}]}}")
MINUTE = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': "
          "[{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaValue': '5'}]}]}}")
OVERLOADED = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"


class FakeClient:
    """Answers or fails per model, and records which models were asked."""

    def __init__(self, outcomes):
        self.outcomes = outcomes  # model -> Exception to raise, or text to answer
        self.asked = []
        self.configs = []
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, model, contents, config):
        self.asked.append(model)
        self.configs.append(config)
        outcome = self.outcomes.get(model, "ok")
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome, model=model)


# ---------- chain ----------

class TestChain:
    def test_newest_flash_first_and_lite_last(self):
        assert chain()[0] == "gemini-3.8-flash"
        assert chain()[-3:] == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]

    def test_first_starts_lower_down_and_reaches_the_top_models_last(self):
        # A backfill starting at 3.6 must not spend 3.8 — the morning run's
        # model — until everything below it is gone.
        order = chain("gemini-3.6-flash")
        assert order[0] == "gemini-3.6-flash"
        assert order[-1] == "gemini-3.8-flash"
        assert sorted(order) == sorted(DEFAULT_CHAIN)

    def test_first_outside_the_chain_goes_before_all_of_it(self):
        assert chain("gemini-9-flash") == ["gemini-9-flash", *DEFAULT_CHAIN]

    def test_env_replaces_the_chain(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODELS", " gemini-a , gemini-b,")
        assert chain() == ["gemini-a", "gemini-b"]


# ---------- per-model settings ----------

class TestConfigFor:
    def test_gemini_25_gets_a_zero_budget(self):
        assert fast_thinking("gemini-2.5-flash").thinking_budget == 0

    def test_gemini_3_gets_minimal_level(self):
        # 3.5 Flash-Lite refuses thinking_budget=0 with a 400.
        for model in ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3-flash-preview"):
            tc = fast_thinking(model)
            assert tc.thinking_budget is None
            assert str(tc.thinking_level).lower().endswith("minimal")

    def test_keeps_the_callers_settings_and_adds_the_timeout(self):
        base = types.GenerateContentConfig(max_output_tokens=3000, temperature=0.4,
                                           response_mime_type="application/json")
        cfg = config_for("gemini-3.8-flash", base, fast=True, timeout=120)
        assert (cfg.max_output_tokens, cfg.temperature, cfg.response_mime_type) == (3000, 0.4, "application/json")
        assert cfg.http_options.timeout == 120_000
        assert base.thinking_config is None  # the caller's object is untouched

    def test_without_fast_thinking_is_left_to_the_model(self):
        cfg = config_for("gemini-3.8-flash", types.GenerateContentConfig(temperature=0.7), timeout=60)
        assert cfg.thinking_config is None


# ---------- classify_error ----------

class TestClassifyError:
    def test_daily_quota(self):
        assert classify_error(RuntimeError(DAILY)) == "daily"

    def test_per_minute_limit_is_only_busy(self):
        assert classify_error(RuntimeError(MINUTE)) == "busy"
        assert classify_error(RuntimeError("429")) == "busy"

    def test_overload(self):
        assert classify_error(RuntimeError(OVERLOADED)) == "busy"

    def test_model_not_offered(self):
        assert classify_error(RuntimeError("404 NOT_FOUND. models/gemini-x is not found")) == "gone"

    def test_timeout(self):
        assert classify_error(TimeoutError("The read operation timed out")) == "slow"

    def test_reads_the_code_attribute_of_api_errors(self):
        err = RuntimeError("quota")
        err.code = 503
        assert classify_error(err) == "busy"

    def test_anything_else_is_the_requests_own_fault(self):
        assert classify_error(ValueError("400 INVALID_ARGUMENT. bad schema")) == "fatal"
        assert classify_error(RuntimeError("down")) == "fatal"


# ---------- generate ----------

class TestGenerate:
    def test_first_model_answers(self):
        client = FakeClient({})
        assert generate(client, "hi").model == "gemini-3.8-flash"
        assert client.asked == ["gemini-3.8-flash"]

    def test_spent_model_hands_over_and_is_not_asked_again(self):
        client = FakeClient({"gemini-3.8-flash": RuntimeError(DAILY)})
        assert generate(client, "one").model == "gemini-3.6-flash"
        assert generate(client, "two").model == "gemini-3.6-flash"
        assert client.asked == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.6-flash"]
        assert "gemini-3.8-flash" in gemini_models.skipped()

    def test_overload_moves_on_but_tries_the_model_again_next_time(self):
        client = FakeClient({"gemini-3.8-flash": RuntimeError(OVERLOADED)})
        generate(client, "one")
        generate(client, "two")
        assert client.asked == ["gemini-3.8-flash", "gemini-3.6-flash"] * 2
        assert gemini_models.skipped() == {}

    def test_an_outage_reaches_only_a_few_models(self):
        # Overload retries count against quota; an outage everywhere must go
        # back to the caller's backoff instead of running the chain dry.
        client = FakeClient({m: RuntimeError(OVERLOADED) for m in DEFAULT_CHAIN})
        with pytest.raises(RuntimeError, match="503"):
            generate(client, "hi")
        assert len(client.asked) == gemini_models.MAX_BUSY_HOPS + 1

    def test_runs_down_to_flash_lite(self):
        outcomes = {m: RuntimeError(DAILY) for m in DEFAULT_CHAIN[:-1]}
        client = FakeClient(outcomes)
        assert generate(client, "hi").model == "gemini-2.5-flash-lite"

    def test_every_model_spent_raises_no_model_left_without_asking_again(self):
        client = FakeClient({m: RuntimeError(DAILY) for m in DEFAULT_CHAIN})
        with pytest.raises(NoModelLeft):
            generate(client, "one")
        asked = len(client.asked)
        with pytest.raises(NoModelLeft):
            generate(client, "two")
        assert len(client.asked) == asked  # nothing left to ask

    def test_no_model_left_is_not_mistaken_for_a_transient_error(self):
        # Callers retry on '429'/'quota'/'503' in the message; this one must not be.
        client = FakeClient({m: RuntimeError(DAILY) for m in DEFAULT_CHAIN})
        with pytest.raises(NoModelLeft) as info:
            generate(client, "hi")
        text = str(info.value).lower()
        assert not any(w in text for w in ("429", "quota", "503", "500", "overloaded"))

    def test_a_bad_request_is_raised_at_once(self):
        client = FakeClient({"gemini-3.8-flash": ValueError("400 INVALID_ARGUMENT")})
        with pytest.raises(ValueError):
            generate(client, "hi")
        assert client.asked == ["gemini-3.8-flash"]

    def test_fast_settings_follow_the_model_that_answers(self):
        client = FakeClient({m: RuntimeError(DAILY) for m in DEFAULT_CHAIN[:3]})
        generate(client, "hi", types.GenerateContentConfig(temperature=0.1), fast=True)
        # 3.8 / 3.6 / 3-preview were asked with a level, 2.5-flash with a budget
        assert client.asked[-1] == "gemini-2.5-flash"
        assert client.configs[-1].thinking_config.thinking_budget == 0
        assert client.configs[0].thinking_config.thinking_budget is None

    def test_first_starts_there(self):
        client = FakeClient({})
        generate(client, "hi", first="gemini-3-flash-preview")
        assert client.asked == ["gemini-3-flash-preview"]
