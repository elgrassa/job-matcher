"""Tests for LLM scorer."""

import pytest

from job_matcher.scoring.llm_scorer import (
    build_scoring_prompt,
    parse_scoring_response,
)


class TestBuildPrompt:
    def test_contains_cv_and_job(self, sample_job_model, sample_cv_model):
        prompt = build_scoring_prompt(sample_job_model, sample_cv_model, ["java"])
        assert sample_cv_model.content in prompt
        assert sample_job_model.title in prompt
        assert "java" in prompt


class TestParseResponse:
    def test_valid(self):
        text = '{"semantic_score": 0.85, "reasoning": "Strong fit", "green_flags": ["java"], "red_flags": ["no fintech"]}'
        result = parse_scoring_response(text)
        assert result.semantic_score == 0.85
        assert "Strong fit" in result.reasoning
        assert "java" in result.green_flags

    def test_strips_markdown_fences(self):
        text = '```json\n{"semantic_score": 0.7, "reasoning": "OK", "green_flags": [], "red_flags": []}\n```'
        result = parse_scoring_response(text)
        assert result.semantic_score == 0.7

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_scoring_response("Not JSON")


class TestScoreOne:
    @pytest.mark.asyncio
    async def test_calls_anthropic(
        self, mock_anthropic_client, sample_job_model, sample_cv_model, tmp_path, monkeypatch
    ):
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import CostLedgerEntry
        from job_matcher.scoring.llm_scorer import LlmScorer
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        store = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", store)
        tracker = CostTracker()

        response = '{"semantic_score": 0.82, "reasoning": "Good", "green_flags": ["java"], "red_flags": []}'
        client = mock_anthropic_client(responses=[response])
        scorer = LlmScorer(client, "claude-haiku-4-5-20251001", tracker)
        result = await scorer.score_one(sample_job_model, sample_cv_model, ["java"])

        assert result.semantic_score == 0.82
        assert client.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_parse_error(
        self, mock_anthropic_client, sample_job_model, sample_cv_model, tmp_path, monkeypatch
    ):
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import CostLedgerEntry
        from job_matcher.scoring.llm_scorer import LlmScorer
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        store = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", store)
        tracker = CostTracker()

        # First response is bad, second is good
        client = mock_anthropic_client(responses=[
            "This is not JSON",
            '{"semantic_score": 0.5, "reasoning": "Retry worked", "green_flags": [], "red_flags": []}',
        ])
        scorer = LlmScorer(client, "claude-haiku-4-5-20251001", tracker)
        result = await scorer.score_one(sample_job_model, sample_cv_model, [])

        assert result.semantic_score == 0.5
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_on_double_parse_error(
        self, mock_anthropic_client, sample_job_model, sample_cv_model, tmp_path, monkeypatch
    ):
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import CostLedgerEntry
        from job_matcher.scoring.llm_scorer import LlmScorer
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        store = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", store)
        tracker = CostTracker()

        client = mock_anthropic_client(responses=["bad1", "bad2"])
        scorer = LlmScorer(client, "claude-haiku-4-5-20251001", tracker)
        result = await scorer.score_one(sample_job_model, sample_cv_model, [])

        assert result.semantic_score == 0.0
        assert "LLM parse error" in result.reasoning
