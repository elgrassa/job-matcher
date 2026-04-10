"""LinkedIn scraper via harvestapi/linkedin-job-search actor."""

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, ClassVar, Literal

from job_matcher.models import RawJob
from job_matcher.scrapers.base import Scraper

logger = logging.getLogger(__name__)


class LinkedInScraper(Scraper):
    platform_name: ClassVar[Literal["linkedin"]] = "linkedin"

    def scrape(
        self,
        max_results: int | None = None,
        since: timedelta | None = None,
    ) -> Iterator[RawJob]:
        run_input = dict(self.config.default_input)
        if since is not None:
            run_input["postedWithinDays"] = max(1, since.days)

        actor_id = self.config.actor_id
        if not actor_id:
            raise ValueError("LinkedIn config missing actor_id")

        dataset_id = self._run_actor(actor_id, run_input)
        for item in self._iterate_dataset(dataset_id, max_results):
            try:
                yield self.parse_item(item)
            except Exception:
                logger.warning("Failed to parse LinkedIn item, skipping", exc_info=True)

    def parse_item(self, raw: dict[str, Any]) -> RawJob:
        # company is a nested dict: {"name": "...", "linkedinUrl": "..."}
        company_obj = raw.get("company") or {}
        company_name = (
            company_obj.get("name") if isinstance(company_obj, dict) else str(company_obj)
        )

        # location is a nested dict: {"linkedinText": "Warsaw, Poland", ...}
        location_obj = raw.get("location") or {}
        if isinstance(location_obj, dict):
            location_text = location_obj.get("linkedinText")
        else:
            location_text = str(location_obj)

        # salary is a dict: {"text": "...", "min": N, "max": N}
        salary_obj = raw.get("salary") or {}
        salary_raw = None
        if isinstance(salary_obj, dict):
            salary_text = salary_obj.get("text")
            salary_min = salary_obj.get("min")
            salary_max = salary_obj.get("max")
            if salary_text:
                salary_raw = salary_text
            elif salary_min or salary_max:
                parts = []
                if salary_min:
                    parts.append(str(salary_min))
                if salary_max:
                    parts.append(str(salary_max))
                salary_raw = " - ".join(parts)
        elif salary_obj:
            salary_raw = str(salary_obj)

        # employmentType: "full_time" -> "Permanent", "contract" -> "Contract", etc.
        employment_raw = raw.get("employmentType") or None

        return RawJob(
            platform="linkedin",
            platform_job_id=str(raw.get("id", "")) or None,
            url=raw.get("linkedinUrl") or raw.get("url") or raw.get("link") or "",
            title=raw.get("title") or "",
            company=company_name or "",
            location=location_text or None,
            description=raw.get("descriptionText") or raw.get("description") or "",
            salary_raw=salary_raw,
            employment_type_raw=employment_raw,
            remote_type_raw=raw.get("workplaceType") or None,
            posted_at_raw=raw.get("postedDate") or raw.get("postedAt") or None,
            raw=raw,
        )
