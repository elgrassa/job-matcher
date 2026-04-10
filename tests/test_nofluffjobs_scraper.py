"""Tests for NoFluffJobs scraper parser and scrape flow."""

from unittest.mock import MagicMock

from job_matcher.scrapers.nofluffjobs import NoFluffJobsScraper


def _make_scraper():
    return NoFluffJobsScraper.__new__(NoFluffJobsScraper)


def _sample_item(**overrides) -> dict:
    base = {
        "slug": "senior-qa-engineer-acme-remote",
        "title": "Senior QA Engineer",
        "company": {"name": "Acme"},
        "location": {"city": "Wrocław", "country": "Poland"},
        "salary": {"from": 22000, "to": 32000, "currency": "PLN", "type": "month"},
        "employmentType": "b2b",
        "remote": True,
        "seniority": ["senior"],
        "description": "Looking for a Senior QA Engineer.",
        "requirements": [{"value": "Java"}, {"value": "Selenium"}],
        "posted": "2026-04-09T12:00:00Z",
        "url": "https://nofluffjobs.com/job/senior-qa-engineer-acme-remote",
    }
    base.update(overrides)
    return base


class TestParseItem:
    def test_extracts_title_and_company(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.title == "Senior QA Engineer"
        assert raw_job.company == "Acme"
        assert raw_job.platform == "nofluffjobs"

    def test_extracts_slug_as_platform_job_id(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.platform_job_id == "senior-qa-engineer-acme-remote"

    def test_extracts_location(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.location == "Wrocław, Poland"

    def test_extracts_salary(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.salary_raw is not None
        assert "22000" in raw_job.salary_raw
        assert "32000" in raw_job.salary_raw
        assert "PLN" in raw_job.salary_raw

    def test_handles_missing_salary(self):
        scraper = _make_scraper()
        item = _sample_item(salary={})
        raw_job = scraper.parse_item(item)
        assert raw_job.salary_raw is None

    def test_handles_string_company(self):
        scraper = _make_scraper()
        item = _sample_item(company="Plain String Corp")
        raw_job = scraper.parse_item(item)
        assert raw_job.company == "Plain String Corp"

    def test_handles_nested_company(self):
        scraper = _make_scraper()
        item = _sample_item(company={"name": "Nested Corp", "logo": "url"})
        raw_job = scraper.parse_item(item)
        assert raw_job.company == "Nested Corp"

    def test_remote_true_maps_to_remote(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item(remote=True))
        assert raw_job.remote_type_raw == "remote"

    def test_remote_false_maps_to_none(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item(remote=False))
        assert raw_job.remote_type_raw is None

    def test_requirements_appended_to_description(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert "Java" in raw_job.description
        assert "Selenium" in raw_job.description
        assert "Required:" in raw_job.description

    def test_handles_missing_requirements(self):
        scraper = _make_scraper()
        item = _sample_item(requirements=[])
        raw_job = scraper.parse_item(item)
        assert "Required:" not in raw_job.description

    def test_handles_location_as_list(self):
        scraper = _make_scraper()
        item = _sample_item(location=[{"city": "Warsaw"}, {"city": "Remote"}])
        raw_job = scraper.parse_item(item)
        assert raw_job.location == "Warsaw"

    def test_handles_missing_location(self):
        scraper = _make_scraper()
        item = _sample_item(location=None)
        raw_job = scraper.parse_item(item)
        assert raw_job.location is None

    def test_generates_url_from_slug(self):
        scraper = _make_scraper()
        item = _sample_item(url=None)
        raw_job = scraper.parse_item(item)
        assert "nofluffjobs.com/job/senior-qa-engineer-acme-remote" in raw_job.url

    def test_preserves_raw_dict(self):
        scraper = _make_scraper()
        item = _sample_item()
        raw_job = scraper.parse_item(item)
        assert raw_job.raw == item

    def test_extracts_posted_at(self):
        scraper = _make_scraper()
        raw_job = scraper.parse_item(_sample_item())
        assert raw_job.posted_at_raw == "2026-04-09T12:00:00Z"


class TestScrapeFlow:
    def test_single_phase_scrape(self):
        from job_matcher.config import PlatformConfig

        config = PlatformConfig(
            enabled=True,
            actor_id="getdataforme/nofluffjobs-profile-scraper",
            default_input={"search_terms": ["sdet"]},
        )
        scraper = NoFluffJobsScraper("fake-token", config)

        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds-nfj",
        }
        mock_client.dataset.return_value.iterate_items.return_value = iter(
            [_sample_item(), _sample_item(slug="another-job")]
        )
        scraper.client = mock_client

        results = list(scraper.scrape())
        assert len(results) == 2
        assert mock_client.actor.return_value.call.call_count == 1

    def test_respects_max_results(self):
        from job_matcher.config import PlatformConfig

        config = PlatformConfig(
            enabled=True,
            actor_id="test-actor",
            default_input={},
        )
        scraper = NoFluffJobsScraper("fake-token", config)

        mock_client = MagicMock()
        mock_client.actor.return_value.call.return_value = {
            "status": "SUCCEEDED",
            "defaultDatasetId": "ds-nfj",
        }
        mock_client.dataset.return_value.iterate_items.return_value = iter(
            [_sample_item(slug=f"job-{i}") for i in range(10)]
        )
        scraper.client = mock_client

        results = list(scraper.scrape(max_results=3))
        assert len(results) == 3
