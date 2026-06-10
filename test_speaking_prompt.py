"""
Tests for the daily speaking-output prompt (Phase 0 of daily-speaking-output).

Pure-function tests only. The live Gemini call (generate_speaking_prompt) is
exercised with a mocked client.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from write_articles import (
    build_speaking_prompt_request,
    parse_speaking_prompt,
    generate_speaking_prompt,
)


SAMPLE_ARTICLE = {
    "title": "China's Dirty Money Problem, Explained",
    "channel": "Vox",
    "url": "https://youtube.com/watch?v=x",
    "article": "# Flying money\n\nThe scheme is hard to trace because brokers exploit loopholes...",
}


# ---------- build_speaking_prompt_request ----------

class TestBuildRequest:
    def test_contains_core_instructions(self):
        p = build_speaking_prompt_request(SAMPLE_ARTICLE)
        # production (own opinion), not recitation
        assert "opinion" in p.lower() or "your own" in p.lower()
        # the scaffolding fields the model must return
        assert "frame" in p.lower()
        assert "expression" in p.lower()
        assert "model" in p.lower()
        # JSON-only
        assert "JSON" in p
        # the article content is embedded for grounding
        assert "Flying money" in p or "hard to trace" in p

    def test_requests_practical_shadow_sentences(self):
        p = build_speaking_prompt_request(SAMPLE_ARTICLE)
        assert "shadow" in p.lower()
        # must demand everyday/practical + level + NOT verbatim
        assert "everyday" in p.lower() or "real life" in p.lower() or "practical" in p.lower()
        assert "B1" in p or "B2" in p
        assert "not" in p.lower()  # not copied verbatim

    def test_embeds_title(self):
        p = build_speaking_prompt_request(SAMPLE_ARTICLE)
        assert "China's Dirty Money Problem, Explained" in p


# ---------- parse_speaking_prompt ----------

VALID_JSON = """{
  "topic": "China's Dirty Money Problem",
  "question_ko": "이 돈세탁이 왜 막기 어렵다고 생각해? 영어로 한 문장 말해봐.",
  "frame": "I think ___ because ___.",
  "expressions": [
    {"en": "hard to trace", "ko": "추적하기 어렵다"},
    {"en": "exploit a loophole", "ko": "허점을 악용하다"}
  ],
  "model": "I think it's hard to stop because the money is hard to trace.",
  "shadow": [
    {"en": "I need to keep track of my spending.", "ko": "지출을 잘 관리해야 해."},
    {"en": "It's hard to trust people you don't know.", "ko": "모르는 사람을 믿기는 어려워."},
    {"en": "Let's keep this between us.", "ko": "이건 우리끼리만 알자."}
  ]
}"""


class TestParse:
    def test_clean_json(self):
        d = parse_speaking_prompt(VALID_JSON)
        assert d["topic"] == "China's Dirty Money Problem"
        assert d["question_ko"].startswith("이 돈세탁")
        assert d["frame"] == "I think ___ because ___."
        assert d["model"].startswith("I think it's hard")
        assert len(d["expressions"]) == 2
        assert d["expressions"][0] == {"en": "hard to trace", "ko": "추적하기 어렵다"}
        assert len(d["shadow"]) == 3
        assert d["shadow"][0] == {"en": "I need to keep track of my spending.", "ko": "지출을 잘 관리해야 해."}

    def test_shadow_clamped_and_filtered(self):
        text = """{
          "question_ko":"q","frame":"f","model":"m",
          "shadow":[
            {"en":"One.","ko":"하나"},{"en":"Two.","ko":"둘"},
            {"en":"Three.","ko":"셋"},{"en":"Four.","ko":"넷"},{"en":"Five.","ko":"다섯"},
            {"ko":"no en"}, "notdict", {"en":"  "}
          ]
        }"""
        d = parse_speaking_prompt(text)
        # capped at 4, malformed dropped
        assert len(d["shadow"]) == 4
        assert all(s["en"].strip() for s in d["shadow"])

    def test_shadow_optional_defaults_empty(self):
        d = parse_speaking_prompt('{"question_ko":"q","frame":"f","model":"m"}')
        assert d["shadow"] == []

    def test_code_fenced(self):
        d = parse_speaking_prompt("```json\n" + VALID_JSON + "\n```")
        assert d is not None
        assert d["frame"].startswith("I think")

    def test_missing_required_returns_none(self):
        # no question_ko
        bad = '{"frame": "I ___", "model": "x"}'
        assert parse_speaking_prompt(bad) is None
        # no model
        bad2 = '{"question_ko": "q", "frame": "f"}'
        assert parse_speaking_prompt(bad2) is None

    def test_expressions_clamped_to_three(self):
        many = """{
          "question_ko": "q", "frame": "f", "model": "m",
          "expressions": [
            {"en":"a","ko":"1"},{"en":"b","ko":"2"},
            {"en":"c","ko":"3"},{"en":"d","ko":"4"}
          ]
        }"""
        d = parse_speaking_prompt(many)
        assert len(d["expressions"]) == 3

    def test_malformed_expressions_filtered(self):
        d = parse_speaking_prompt("""{
          "question_ko":"q","frame":"f","model":"m",
          "expressions":[{"en":"ok","ko":"좋음"}, {"ko":"no en"}, "notdict", {"en":"  "}]
        }""")
        # only the well-formed one survives
        assert d["expressions"] == [{"en": "ok", "ko": "좋음"}]

    def test_topic_optional_defaults_empty(self):
        d = parse_speaking_prompt('{"question_ko":"q","frame":"f","model":"m"}')
        assert d["topic"] == ""
        assert d["expressions"] == []

    def test_garbage_returns_none(self):
        assert parse_speaking_prompt("not json") is None
        assert parse_speaking_prompt("") is None


# ---------- generate_speaking_prompt (mocked Gemini) ----------

def _mock_resp(text):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=100, candidates_token_count=80, thoughts_token_count=0
        ),
    )


class TestGenerate:
    def test_returns_parsed_prompt(self):
        with patch("write_articles.client") as mock_client, \
             patch("write_articles.time.sleep"):
            mock_client.models.generate_content.return_value = _mock_resp(VALID_JSON)
            d = generate_speaking_prompt([SAMPLE_ARTICLE])
            assert d is not None
            assert d["frame"].startswith("I think")
            # thinking disabled like the other extraction calls
            cfg = mock_client.models.generate_content.call_args.kwargs["config"]
            tc = getattr(cfg, "thinking_config", None)
            assert tc is not None and getattr(tc, "thinking_budget", None) == 0

    def test_empty_articles_returns_none_without_call(self):
        with patch("write_articles.client") as mock_client:
            assert generate_speaking_prompt([]) is None
            mock_client.models.generate_content.assert_not_called()

    def test_bad_model_output_returns_none(self):
        with patch("write_articles.client") as mock_client, \
             patch("write_articles.time.sleep"):
            mock_client.models.generate_content.return_value = _mock_resp("garbage")
            assert generate_speaking_prompt([SAMPLE_ARTICLE]) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
