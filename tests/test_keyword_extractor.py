"""Tests for keyword extractor."""

import pytest

from job_matcher.scoring.keyword_extractor import (
    build_extraction_prompt,
    parse_extraction_response,
)


class TestBuildPrompt:
    def test_contains_job_description(self, sample_job_model):
        prompt = build_extraction_prompt(sample_job_model)
        assert sample_job_model.description in prompt
        assert sample_job_model.title in prompt
        assert sample_job_model.company in prompt


class TestParseResponse:
    def test_valid_json(self):
        text = '{"must_have": ["java", "python"], "nice_to_have": ["docker"]}'
        must, nice = parse_extraction_response(text)
        assert must == ["java", "python"]
        assert nice == ["docker"]

    def test_strips_markdown_fences(self):
        text = '```json\n{"must_have": ["java"], "nice_to_have": []}\n```'
        must, _nice = parse_extraction_response(text)
        assert must == ["java"]

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_extraction_response("This is not JSON at all")

    def test_empty_lists_valid(self):
        text = '{"must_have": [], "nice_to_have": []}'
        must, nice = parse_extraction_response(text)
        assert must == []
        assert nice == []


class TestExtract:
    @pytest.mark.asyncio
    async def test_calls_anthropic_once(
        self, mock_anthropic_client, sample_job_model, tmp_path, monkeypatch
    ):
        from job_matcher.cost_tracker import CostTracker
        from job_matcher.models import CostLedgerEntry
        from job_matcher.scoring.keyword_extractor import KeywordExtractor
        from job_matcher.storage import JsonStore

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        store = JsonStore(
            file_path=tmp_path / "cost.json", model=CostLedgerEntry, lock_dir=lock_dir
        )
        monkeypatch.setattr("job_matcher.cost_tracker.cost_store", store)
        tracker = CostTracker()

        client = mock_anthropic_client(
            responses=['{"must_have": ["java", "python"], "nice_to_have": ["docker"]}']
        )
        extractor = KeywordExtractor(client, "claude-haiku-4-5-20251001", tracker)
        result = await extractor.extract(sample_job_model)

        assert result.job_id == sample_job_model.id
        assert "java" in result.must_have
        assert client.call_count == 1
