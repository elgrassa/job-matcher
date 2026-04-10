"""Maps platform name to scraper class."""

from job_matcher.config import PlatformConfig, PlatformsConfig
from job_matcher.scrapers.base import Scraper
from job_matcher.scrapers.linkedin import LinkedInScraper

_SCRAPER_CLASSES: dict[str, type[Scraper]] = {
    "linkedin": LinkedInScraper,
}


def get_scraper(platform: str, token: str, config: PlatformConfig) -> Scraper:
    """Factory. Raises KeyError on unknown platform."""
    cls = _SCRAPER_CLASSES[platform]
    return cls(token, config)


def list_enabled_scrapers(
    platforms_config: PlatformsConfig,
    apify_token: str,
) -> list[Scraper]:
    """Return instances for every enabled platform in config."""
    scrapers: list[Scraper] = []
    platform_map = {
        "linkedin": platforms_config.linkedin,
        "justjoin": platforms_config.justjoin,
        "nofluffjobs": platforms_config.nofluffjobs,
    }
    for name, config in platform_map.items():
        if config.enabled and name in _SCRAPER_CLASSES:
            scrapers.append(get_scraper(name, apify_token, config))
    return scrapers
