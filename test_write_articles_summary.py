"""
Tests for per-episode summary generation diagnostics and truncation handling.

Focus: helpers around `generate_summary()` — not the live Gemini call, which
is mocked. These tests defend against the regression where Gemini 2.5 Flash
thinking-tokens silently consumed the output budget.
"""

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from write_articles import (
    _extract_finish_reason,
    _is_truncated_finish,
    _log_usage_metadata,
    _trim_to_sentence_boundary,
    generate_summary,
)


# ---------- _extract_finish_reason ----------

class TestExtractFinishReason:
    def test_handles_enum_with_name(self):
        resp = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name='MAX_TOKENS'))]
        )
        assert _extract_finish_reason(resp) == 'MAX_TOKENS'

    def test_handles_plain_string(self):
        resp = SimpleNamespace(candidates=[SimpleNamespace(finish_reason='STOP')])
        assert _extract_finish_reason(resp) == 'STOP'

    def test_handles_int(self):
        # Some SDKs report enum-by-int
        resp = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=2)])
        assert _extract_finish_reason(resp) == '2'

    def test_missing_candidates_returns_empty(self):
        resp = SimpleNamespace(candidates=[])
        assert _extract_finish_reason(resp) == ''

    def test_none_finish_reason_returns_empty(self):
        resp = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=None)])
        assert _extract_finish_reason(resp) == ''


# ---------- _is_truncated_finish ----------

class TestIsTruncatedFinish:
    def test_max_tokens_is_truncated(self):
        assert _is_truncated_finish('MAX_TOKENS') is True
        assert _is_truncated_finish('FINISH_REASON_MAX_TOKENS') is True

    def test_length_alias_is_truncated(self):
        assert _is_truncated_finish('LENGTH') is True

    def test_stop_is_not_truncated(self):
        assert _is_truncated_finish('STOP') is False
        assert _is_truncated_finish('FINISH_REASON_STOP') is False

    def test_empty_is_not_truncated(self):
        # Lack of signal means we cannot claim truncation
        assert _is_truncated_finish('') is False
        assert _is_truncated_finish(None) is False


# ---------- _trim_to_sentence_boundary ----------

class TestTrimToSentenceBoundary:
    def test_keeps_full_text_when_ends_with_period(self):
        s = "First sentence. Second sentence."
        assert _trim_to_sentence_boundary(s) == s

    def test_trims_mid_word_tail(self):
        # Mimics the real bug: "...much like early" with no terminator
        s = "First sentence finished. Second sentence cut mid-w"
        result = _trim_to_sentence_boundary(s)
        assert result == "First sentence finished."

    def test_handles_korean_period(self):
        s = "첫 문장입니다. 둘째 문장은 잘렸"
        result = _trim_to_sentence_boundary(s)
        assert result == "첫 문장입니다."

    def test_preserves_text_when_cut_too_aggressive(self):
        # Only a tiny terminator near the start — don't lose most of the text
        s = "Hi. " + "x" * 100
        result = _trim_to_sentence_boundary(s)
        assert result == s  # original returned

    def test_empty_input(self):
        assert _trim_to_sentence_boundary('') == ''


# ---------- _log_usage_metadata ----------

class TestLogUsageMetadata:
    def test_logs_thinking_tokens(self, capsys):
        um = SimpleNamespace(
            prompt_token_count=300,
            candidates_token_count=120,
            thoughts_token_count=2100,
        )
        resp = SimpleNamespace(usage_metadata=um)
        _log_usage_metadata(resp, label='Summary')
        out = capsys.readouterr().out
        assert 'prompt=300' in out
        assert 'output=120' in out
        assert 'thinking=2100' in out

    def test_missing_usage_metadata_does_not_raise(self):
        resp = SimpleNamespace(usage_metadata=None)
        _log_usage_metadata(resp)  # must not raise

    def test_handles_alternate_attribute_name(self, capsys):
        # Some SDK versions expose `thinking_token_count` instead
        um = SimpleNamespace(
            prompt_token_count=50,
            candidates_token_count=80,
            thinking_token_count=900,
        )
        resp = SimpleNamespace(usage_metadata=um)
        _log_usage_metadata(resp)
        out = capsys.readouterr().out
        assert 'thinking=900' in out


# ---------- generate_summary integration with mocked client ----------

def _mock_response(text, finish='STOP', thoughts=10):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))],
        usage_metadata=SimpleNamespace(
            prompt_token_count=500,
            candidates_token_count=200,
            thoughts_token_count=thoughts,
        ),
    )


@pytest.fixture
def video():
    return {
        'title': 'Test Video',
        'channel': 'TestCh',
        'url': 'https://youtube.com/watch?v=t',
        'transcript': 'Hello world. ' * 50,
    }


class TestGenerateSummaryConfig:
    def test_thinking_is_disabled_in_config(self, video):
        """Phase 2 contract: summary calls must set thinking_budget=0."""
        with patch('write_articles.client') as mock_client, \
             patch('write_articles.time.sleep'):
            mock_client.models.generate_content.return_value = _mock_response(
                "Complete summary ending properly."
            )
            generate_summary(video, language='en', is_first=True)

            assert mock_client.models.generate_content.called
            kwargs = mock_client.models.generate_content.call_args.kwargs
            cfg = kwargs['config']
            # The config must carry a ThinkingConfig with budget 0
            thinking_cfg = getattr(cfg, 'thinking_config', None)
            assert thinking_cfg is not None, "thinking_config must be set"
            budget = getattr(thinking_cfg, 'thinking_budget', None)
            assert budget == 0, f"thinking_budget must be 0, got {budget}"

    def test_token_cap_is_at_least_4000(self, video):
        with patch('write_articles.client') as mock_client, \
             patch('write_articles.time.sleep'):
            mock_client.models.generate_content.return_value = _mock_response("ok.")
            generate_summary(video, language='en', is_first=True)
            cfg = mock_client.models.generate_content.call_args.kwargs['config']
            assert getattr(cfg, 'max_output_tokens', 0) >= 4000


class TestGenerateSummaryTruncation:
    def test_complete_response_returned_as_is(self, video):
        with patch('write_articles.client') as mock_client, \
             patch('write_articles.time.sleep'):
            mock_client.models.generate_content.return_value = _mock_response(
                "Complete summary. Second sentence here."
            )
            result = generate_summary(video, language='en', is_first=True)
            assert result == "Complete summary. Second sentence here."
            # Only one API call when not truncated
            assert mock_client.models.generate_content.call_count == 1

    def test_truncated_response_triggers_retry_with_doubled_cap(self, video):
        """Phase 3 contract: MAX_TOKENS triggers one retry at doubled cap."""
        truncated = _mock_response(
            "First sentence done. Second sentence cut mid-wo",
            finish='MAX_TOKENS',
        )
        complete = _mock_response(
            "First sentence done. Second sentence is complete now."
        )
        with patch('write_articles.client') as mock_client, \
             patch('write_articles.time.sleep'):
            mock_client.models.generate_content.side_effect = [truncated, complete]
            result = generate_summary(video, language='en', is_first=True)

            assert mock_client.models.generate_content.call_count == 2
            # Retry config must have a larger cap than the first call
            first_cap = mock_client.models.generate_content.call_args_list[0].kwargs['config'].max_output_tokens
            second_cap = mock_client.models.generate_content.call_args_list[1].kwargs['config'].max_output_tokens
            assert second_cap >= first_cap * 2
            # Result is the complete second response
            assert result == "First sentence done. Second sentence is complete now."

    def test_truncated_twice_falls_back_to_sentence_trim(self, video):
        """Both attempts truncated → trim to last complete sentence, never mid-word."""
        first = _mock_response(
            "First sentence done. Second sentence cut mid-wo",
            finish='MAX_TOKENS',
        )
        second = _mock_response(
            "First sentence done. Second sentence also cut mid-wo",
            finish='MAX_TOKENS',
        )
        with patch('write_articles.client') as mock_client, \
             patch('write_articles.time.sleep'):
            mock_client.models.generate_content.side_effect = [first, second]
            result = generate_summary(video, language='en', is_first=True)
            assert result == "First sentence done."
            assert mock_client.models.generate_content.call_count == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
