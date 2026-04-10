"""Shared pytest fixtures."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

_DEFAULT_RESPONSE = (
    '{"semantic_score": 0.75, "reasoning": "Good fit",'
    ' "green_flags": ["java"], "red_flags": []}'
)


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory with lock subdirectory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".locks").mkdir()
    return data_dir


@pytest.fixture
def sample_job() -> dict:
    """A minimal valid Job dict for testing."""
    now = datetime.now(UTC).isoformat()
    return {
        "id": "a3f7c2b8e1d94f56",
        "title": "Senior SDET",
        "company": "Acme Corp",
        "location": "Wroclaw, Poland",
        "description": "We are looking for a Senior SDET with Java and Python experience.",
        "salary_min": 320.0,
        "salary_max": 480.0,
        "salary_currency": "EUR",
        "salary_period": "day",
        "employment_type": "b2b",
        "remote_type": "remote",
        "seniority": "senior",
        "posted_at": now,
        "first_seen_at": now,
        "last_seen_at": now,
        "scraped_at": now,
    }


@pytest.fixture
def sample_cv() -> dict:
    """A minimal valid CvVersion dict for testing."""
    return {
        "id": "senior_sdet",
        "name": "Senior SDET / QA Architect",
        "file_path": "cvs/senior_sdet.md",
        "content_hash": "sha256:" + "a" * 64,
        "content": "Senior SDET with 15 years of experience in Java and Python.",
        "char_count": 60,
        "loaded_at": datetime.now(UTC).isoformat(),
        "enabled": True,
    }


@pytest.fixture
def mock_anthropic_client():
    """A mock AsyncAnthropic client for testing LLM calls."""

    class MockAsyncAnthropic:
        def __init__(self, responses: list[str] | None = None):
            self._responses = iter(responses or [_DEFAULT_RESPONSE])
            self.call_count = 0

        class _MockMessages:
            def __init__(self, parent: "MockAsyncAnthropic"):
                self.parent = parent

            async def create(self, **kwargs):
                del kwargs
                self.parent.call_count += 1
                text = next(self.parent._responses)
                return SimpleNamespace(
                    content=[SimpleNamespace(text=text)],
                    usage=SimpleNamespace(input_tokens=1500, output_tokens=200),
                )

        @property
        def messages(self):
            return self._MockMessages(self)

    return MockAsyncAnthropic


@pytest.fixture
def mock_apify_client():
    """A mock ApifyClient for testing scrapers."""

    class MockApifyClient:
        def __init__(self, dataset_items: list[dict] | None = None):
            self._dataset_items = dataset_items or []

        def actor(self, _actor_id: str):
            class MockActor:
                def call(self, run_input=None):
                    del run_input
                    return {
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "mock-dataset-id",
                    }

            return MockActor()

        def dataset(self, _dataset_id: str):
            items = self._dataset_items

            class MockDataset:
                def iterate_items(self):
                    return iter(items)

            return MockDataset()

    return MockApifyClient
