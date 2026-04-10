"""Tests for JustJoin scraper parser and scrape flow."""

from unittest.mock import MagicMock

from job_matcher.scrapers.justjoin import JustJoinScraper


def _make_scraper():
    """Create a JustJoinScraper without hitting __init__ (for parse_item tests)."""
    return JustJoinScraper.__new__(JustJoinScraper)


def _sample_item(**overrides) -> dict:
    base = {
        "slug": "senior-sdet-acme-wroclaw",
        "title": "Senior SDET",
        "companyName": "Acme Sp. z o.o.",
        "city": "Wrocław",
        "countryCode": "PL",
        "workplaceType": "remote",
        "employmentTypes": [
            {
                "type": "b2b",
                "salary": {"from": 25000, "to": 35000, "currency": "PLN"},
            }
        ],
        "body": "We are looking for a Senior SDET with Java and Python.",
        "publishedAt": "2026-04-08T10:00:00Z",
        "link": "https://justjoin.it/offers/senior-sdet-acme-wroclaw",
    }
    base.update(overrides)
    return base


class TestParseItem:
    def test_extracts_title_and_company(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.title == "Senior SDET"
        assert raw_job.company == "Acme Sp. z o.o."
        assert raw_job.platform == "justjoin"

    def test_extracts_slug_as_platform_job_id(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.platform_job_id == "senior-sdet-acme-wroclaw"

    def test_extracts_location_with_country(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.location == "Wrocław, PL"

    def test_extracts_salary_from_employment_types(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.salary_raw is not None
        assert "25000" in raw_job.salary_raw
        assert "35000" in raw_job.salary_raw
        assert "PLN" in raw_job.salary_raw

    def test_handles_missing_salary(self):
        scraper = _make_scraper()
        item = _sample_item(employmentTypes=[{"type": "b2b", "salary": {}}])
        raw_job = scraper.parse_item(item)
        assert raw_job.salary_raw is None

    def test_handles_empty_employment_types(self):
        scraper = _make_scraper()
        item = _sample_item(employmentTypes=[])
        raw_job = scraper.parse_item(item)
        assert raw_job.salary_raw is None
        assert raw_job.employment_type_raw is None

    def test_handles_nested_company_dict(self):
        scraper = _make_scraper()
        item = _sample_item(companyName={"name": "Nested Corp"})
        raw_job = scraper.parse_item(item)
        assert raw_job.company == "Nested Corp"

    def test_handles_missing_location(self):
        scraper = _make_scraper()
        item = _sample_item(city=None, countryCode=None)
        raw_job = scraper.parse_item(item)
        assert raw_job.location is None

    def test_extracts_url(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert "justjoin.it" in raw_job.url

    def test_generates_url_from_slug_when_missing(self):
        scraper = _make_scraper()
        item = _sample_item(link=None)
        raw_job = scraper.parse_item(item)
        assert "justjoin.it/offers/senior-sdet-acme-wroclaw" in raw_job.url

    def test_preserves_raw_dict(self):
        scraper = _make_scraper()
        item = _sample_item()
        raw_job = scraper.parse_item(item)
        assert raw_job.raw == item

    def test_extracts_remote_type(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.remote_type_raw == "remote"

    def test_extracts_posted_at(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.posted_at_raw == "2026-04-08T10:00:00Z"


class TestScrapeFlow:
    def test_two_phase_scrape(self):
        from job_matcher.config import PlatformConfig

        config = PlatformConfig(
            enabled=True,
            search_actor_id="stealth_mode/justjoin-jobs-search-scraper",
            details_actor_id="stealth_mode/justjoin-jobs-details-scraper",
            default_input={"categories": ["testing"]},
        )
        scraper = JustJoinScraper("fake-token", config)

        mock_client = MagicMock()
        # Phase 1: search returns slugs
        mock_client.actor.return_value.call.side_effect = [
            {"status": "SUCCEEDED", "defaultDatasetId": "ds-search"},
            {"status": "SUCCEEDED", "defaultDatasetId": "ds-details"},
        ]
        mock_client.dataset.return_value.iterate_items.side_effect = [
            iter([{"slug": "job-a"}, {"slug": "job-b"}]),
            iter([_sample_item(slug="job-a"), _sample_item(slug="job-b")]),
        ]
        scraper.client = mock_client

        results = list(scraper.scrape())
        assert len(results) == 2
        assert mock_client.actor.return_value.call.call_count == 2

    def test_empty_search_returns_nothing(self):
        from job_matcher.config import PlatformConfig

        config = PlatformConfig(
            enabled=True,
            search_actor_id="search",
            details_actor_id="details",
            default_input={},
        )
        scraper = JustJoinScraper("fake-token", config)

        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds-empty",
        }
        mock_client.dataset.return_value.iterate_items.return_value = iter([])
        scraper.client = mock_client

        results = list(scraper.scrape())
        assert len(results) == 0
        # Only search call should happen, no details call
        assert mock_client.actor.return_value.call.call_count == 1
