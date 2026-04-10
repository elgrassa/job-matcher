"""Shared pytest fixtures."""

from pathlib import Path
from types import SimpleNamespace

import pytest

FIXED_TIMESTAMP = "2026-04-10T10:00:00+00:00"

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
        "posted_at": FIXED_TIMESTAMP,
        "first_seen_at": FIXED_TIMESTAMP,
        "last_seen_at": FIXED_TIMESTAMP,
        "scraped_at": FIXED_TIMESTAMP,
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
        "loaded_at": FIXED_TIMESTAMP,
        "enabled": True,
    }


@pytest.fixture
def mock_anthropic_client():
    """A mock AsyncAnthropic client factory for testing LLM calls.

    Usage: client = mock_anthropic_client(responses=[...])
    Raises AssertionError (not StopIteration) when responses are exhausted.
    """

    class MockAsyncAnthropic:
        def __init__(
            self,
            responses: list[str] | None = None,
            errors: dict[int, Exception] | None = None,
        ):
            self._responses = list(responses or [_DEFAULT_RESPONSE])
            self._errors = errors or {}
            self.call_count = 0

        class _MockMessages:
            def __init__(self, parent: "MockAsyncAnthropic"):
                self.parent = parent

            async def create(self, **kwargs):
                del kwargs
                idx = self.parent.call_count
                self.parent.call_count += 1
                if idx in self.parent._errors:
                    raise self.parent._errors[idx]
                assert idx < len(self.parent._responses), (
                    f"MockAsyncAnthropic exhausted: {idx + 1} calls but only "
                    f"{len(self.parent._responses)} responses provided"
                )
                text = self.parent._responses[idx]
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
    """A mock ApifyClient factory for testing scrapers.

    Usage: client = mock_apify_client(dataset_items=[...])
    Pass actor_error=Exception(...) to simulate actor run failure.
    """

    class MockApifyClient:
        def __init__(
            self,
            dataset_items: list[dict] | None = None,
            actor_error: Exception | None = None,
        ):
            self._dataset_items = dataset_items or []
            self._actor_error = actor_error
            self.actor_calls: list[dict] = []

        def actor(self, actor_id: str):
            parent = self

            class MockActor:
                def call(self, run_input=None):
                    parent.actor_calls.append(
                        {"actor_id": actor_id, "run_input": run_input}
                    )
                    if parent._actor_error:
                        raise parent._actor_error
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
