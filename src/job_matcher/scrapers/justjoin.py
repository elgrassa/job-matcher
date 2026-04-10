"""justjoin.it scraper via stealth_mode actors (two-phase: search + details)."""

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, ClassVar, Literal

from job_matcher.models import RawJob
from job_matcher.scrapers.base import Scraper

logger = logging.getLogger(__name__)


class JustJoinScraper(Scraper):
    platform_name: ClassVar[Literal["justjoin"]] = "justjoin"

    def scrape(
        self,
        max_results: int | None = None,
        since: timedelta | None = None,
    ) -> Iterator[RawJob]:
        search_actor = self.config.search_actor_id
        details_actor = self.config.details_actor_id
        if not search_actor or not details_actor:
            raise ValueError(
                "JustJoin config requires both search_actor_id and details_actor_id"
            )

        # Phase 1: search → collect slugs
        search_input = dict(self.config.default_input)
        dataset_id = self._run_actor(search_actor, search_input)

        slugs: list[str] = []
        for item in self._iterate_dataset(dataset_id, max_results):
            slug = item.get("slug") or item.get("id") or ""
            if slug:
                slugs.append(slug)

        if not slugs:
            logger.warning("JustJoin search returned 0 slugs")
            return

        logger.info("JustJoin search returned %d slugs, fetching details", len(slugs))

        # Phase 2: details → full job data
        details_input = {"slugs": slugs}
        details_dataset_id = self._run_actor(details_actor, details_input)

        for item in self._iterate_dataset(details_dataset_id, None):
            try:
                yield self.parse_item(item)
            except Exception as e:
                logger.warning(
                    "Failed to parse JustJoin item (%s: %s), skipping",
                    type(e).__name__, str(e)[:200],
                )

    def parse_item(self, raw: dict[str, Any]) -> RawJob:
        slug = raw.get("slug") or raw.get("id") or ""

        # Company can be nested or a string
        company_obj = raw.get("companyName") or raw.get("company") or {}
        company = company_obj.get("name", "") if isinstance(company_obj, dict) else str(company_obj)

        # Location: city field or address object
        city = raw.get("city") or raw.get("location") or ""
        if isinstance(city, dict):
            city = city.get("name") or city.get("city") or ""
        country = raw.get("countryCode") or ""
        location = f"{city}, {country}".strip(", ") if city else None

        # Salary: employmentTypes is an array of {type, salary: {from, to, currency}}
        salary_raw = None
        emp_types = raw.get("employmentTypes") or []
        employment_type_raw = None
        if isinstance(emp_types, list) and emp_types:
            first = emp_types[0] if isinstance(emp_types[0], dict) else {}
            employment_type_raw = first.get("type")
            sal = first.get("salary") or {}
            if isinstance(sal, dict):
                sal_from = sal.get("from")
                sal_to = sal.get("to")
                currency = sal.get("currency", "PLN")
                if sal_from or sal_to:
                    parts = []
                    if sal_from:
                        parts.append(str(sal_from))
                    if sal_to:
                        parts.append(str(sal_to))
                    salary_raw = f"{' - '.join(parts)} {currency}/month"

        # Remote type
        workplace = raw.get("workplaceType") or raw.get("workplace_type") or ""

        # Description
        description = raw.get("body") or raw.get("description") or ""
        if isinstance(description, dict):
            description = description.get("text") or description.get("html") or ""

        url = raw.get("link") or ""
        if not url and slug:
            url = f"https://justjoin.it/offers/{slug}"

        return RawJob(
            platform="justjoin",
            platform_job_id=slug or None,
            url=url,
            title=raw.get("title") or "",
            company=company or "",
            location=location,
            description=str(description),
            salary_raw=salary_raw,
            employment_type_raw=employment_type_raw,
            remote_type_raw=str(workplace) if workplace else None,
            posted_at_raw=raw.get("publishedAt") or raw.get("createdAt") or None,
            raw=raw,
        )
