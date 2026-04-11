"""Tests for scraper registry factory."""

import pytest

from job_matcher.config import PlatformConfig
from job_matcher.scrapers.justjoin import JustJoinScraper
from job_matcher.scrapers.linkedin import LinkedInScraper
from job_matcher.scrapers.nofluffjobs import NoFluffJobsScraper
from job_matcher.scrapers.registry import get_scraper, list_enabled_scrapers


def _config(**overrides) -> PlatformConfig:
    base = {"enabled": True, "actor_id": "test/actor", "default_input": {}}
    base.update(overrides)
    return PlatformConfig(**base)


class TestGetScraper:
    def test_linkedin(self):
        s = get_scraper("linkedin", "token", _config())
        assert isinstance(s, LinkedInScraper)

    def test_justjoin(self):
        s = get_scraper(
            "justjoin", "token",
            _config(search_actor_id="s", details_actor_id="d"),
        )
        assert isinstance(s, JustJoinScraper)

    def test_nofluffjobs(self):
        s = get_scraper("nofluffjobs", "token", _config())
        assert isinstance(s, NoFluffJobsScraper)

    def test_unknown_platform_raises(self):
        with pytest.raises(KeyError):
            get_scraper("indeed", "token", _config())


class TestListEnabledScrapers:
    def test_returns_only_enabled(self):
        from job_matcher.config import PlatformsConfig

        platforms = PlatformsConfig(
            linkedin=_config(enabled=True),
            justjoin=_config(enabled=False, search_actor_id="s", details_actor_id="d"),
            nofluffjobs=_config(enabled=True),
        )
        scrapers = list_enabled_scrapers(platforms, "token")
        names = [s.platform_name for s in scrapers]
        assert "linkedin" in names
        assert "nofluffjobs" in names
        assert "justjoin" not in names

    def test_all_disabled_returns_empty(self):
        from job_matcher.config import PlatformsConfig

        platforms = PlatformsConfig(
            linkedin=_config(enabled=False),
            justjoin=_config(enabled=False, search_actor_id="s", details_actor_id="d"),
            nofluffjobs=_config(enabled=False),
        )
        scrapers = list_enabled_scrapers(platforms, "token")
        assert len(scrapers) == 0
