"""Tests for LinkedIn scraper parser and scrape flow."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_matcher.scrapers.base import ActorRunFailedError
from job_matcher.scrapers.linkedin import LinkedInScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_raw_linkedin() -> list[dict]:
    with open(FIXTURES_DIR / "sample_raw_linkedin.json") as f:
        return json.load(f)


@pytest.fixture
def linkedin_scraper(mock_apify_client):
    from job_matcher.config import PlatformConfig

    config = PlatformConfig(
        enabled=True,
        actor_id="harvestapi/linkedin-job-search",
        default_input={"titles": ["SDET"], "locations": ["Poland"]},
    )
    scraper = LinkedInScraper("fake-token", config)
    return scraper


class TestParseItem:
    def test_extracts_title_and_company(self, sample_raw_linkedin: list[dict]):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = sample_raw_linkedin[0]
        raw_job = scraper.parse_item(item)
        assert raw_job.title != ""
        assert raw_job.company != ""
        assert raw_job.platform == "linkedin"

    def test_extracts_nested_company_name(self, sample_raw_linkedin: list[dict]):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = sample_raw_linkedin[0]
        raw_job = scraper.parse_item(item)
        # Company should be extracted from nested dict, not be str(dict)
        assert "{" not in raw_job.company

    def test_extracts_nested_location(self, sample_raw_linkedin: list[dict]):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = sample_raw_linkedin[0]
        raw_job = scraper.parse_item(item)
        if raw_job.location:
            assert "{" not in raw_job.location

    def test_handles_missing_salary(self):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = {
            "id": "123",
            "title": "Test",
            "company": {"name": "Acme"},
            "location": {"linkedinText": "Warsaw"},
            "descriptionText": "A job",
            "salary": {"text": None, "min": None, "max": None},
            "linkedinUrl": "https://linkedin.com/jobs/view/123",
        }
        raw_job = scraper.parse_item(item)
        assert raw_job.salary_raw is None

    def test_handles_missing_description(self):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = {
            "id": "456",
            "title": "No Desc Job",
            "company": {"name": "Co"},
            "location": None,
            "linkedinUrl": "https://linkedin.com/jobs/view/456",
        }
        raw_job = scraper.parse_item(item)
        assert raw_job.description == ""

    def test_preserves_raw_dict(self, sample_raw_linkedin: list[dict]):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = sample_raw_linkedin[0]
        raw_job = scraper.parse_item(item)
        assert raw_job.raw == item

    def test_extracts_linkedin_url(self, sample_raw_linkedin: list[dict]):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        item = sample_raw_linkedin[0]
        raw_job = scraper.parse_item(item)
        assert "linkedin.com/jobs/view/" in raw_job.url

    def test_parses_all_fixture_items(self, sample_raw_linkedin: list[dict]):
        scraper = LinkedInScraper.__new__(LinkedInScraper)
        for item in sample_raw_linkedin:
            raw_job = scraper.parse_item(item)
            assert raw_job.title != ""
            assert raw_job.url.startswith("https://")


class TestScrapeFlow:
    def test_iterates_all_items(self, linkedin_scraper: LinkedInScraper):
        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds-123",
        }
        mock_client.dataset.return_value.iterate_items.return_value = iter(
            [
                {
                    "id": "1",
                    "title": "SDET",
                    "company": {"name": "A"},
                    "location": {"linkedinText": "Warsaw"},
                    "descriptionText": "Desc",
                    "linkedinUrl": "https://linkedin.com/jobs/view/1",
                },
                {
                    "id": "2",
                    "title": "QA",
                    "company": {"name": "B"},
                    "location": {"linkedinText": "Remote"},
                    "descriptionText": "Desc2",
                    "linkedinUrl": "https://linkedin.com/jobs/view/2",
                },
            ]
        )
        linkedin_scraper.client = mock_client
        results = list(linkedin_scraper.scrape())
        assert len(results) == 2

    def test_respects_max_results(self, linkedin_scraper: LinkedInScraper):
        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds-123",
        }
        items = [
            {
                "id": str(i),
                "title": f"Job {i}",
                "company": {"name": "Co"},
                "location": {"linkedinText": "Remote"},
                "descriptionText": "Desc",
                "linkedinUrl": f"https://linkedin.com/jobs/view/{i}",
            }
            for i in range(10)
        ]
        mock_client.dataset.return_value.iterate_items.return_value = iter(items)
        linkedin_scraper.client = mock_client
        results = list(linkedin_scraper.scrape(max_results=3))
        assert len(results) == 3

    def test_actor_failure_raises(self, linkedin_scraper: LinkedInScraper):
        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = {
            "status": "FAILED",
            "defaultDatasetId": None,
        }
        linkedin_scraper.client = mock_client
        with pytest.raises(ActorRunFailedError):
            list(linkedin_scraper.scrape())
