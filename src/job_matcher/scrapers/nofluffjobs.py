"""nofluffjobs.com scraper via getdataforme actor."""

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, ClassVar, Literal

from job_matcher.models import RawJob
from job_matcher.scrapers.base import Scraper

logger = logging.getLogger(__name__)


class NoFluffJobsScraper(Scraper):
    platform_name: ClassVar[Literal["nofluffjobs"]] = "nofluffjobs"

    def scrape(
        self,
        max_results: int | None = None,
        since: timedelta | None = None,
    ) -> Iterator[RawJob]:
        actor_id = self.config.actor_id
        if not actor_id:
            raise ValueError("NoFluffJobs config missing actor_id")

        run_input = dict(self.config.default_input)
        dataset_id = self._run_actor(actor_id, run_input)

        for item in self._iterate_dataset(dataset_id, max_results):
            try:
                yield self.parse_item(item)
            except Exception as e:
                logger.warning(
                    "Failed to parse NoFluffJobs item (%s: %s), skipping",
                    type(e).__name__, str(e)[:200],
                )

    def parse_item(self, raw: dict[str, Any]) -> RawJob:
        # ID: slug or id field
        job_id = raw.get("slug") or raw.get("id") or ""

        # Company: may be nested dict or string
        company_obj = raw.get("company") or raw.get("companyName") or {}
        if isinstance(company_obj, dict):
            company = company_obj.get("name") or company_obj.get("companyName") or ""
        else:
            company = str(company_obj)

        # Location: can be nested object or string
        location_obj = raw.get("location") or raw.get("city") or {}
        if isinstance(location_obj, dict):
            city = location_obj.get("city") or location_obj.get("name") or ""
            country = location_obj.get("country") or ""
            location = f"{city}, {country}".strip(", ") if city else None
        elif isinstance(location_obj, list) and location_obj:
            # Some actors return a list of location objects
            first = location_obj[0] if isinstance(location_obj[0], dict) else {}
            city = first.get("city") or str(location_obj[0])
            location = city or None
        else:
            location = str(location_obj) if location_obj else None

        # Salary: various formats
        salary_raw = None
        salary_obj = raw.get("salary") or {}
        if isinstance(salary_obj, dict):
            sal_from = salary_obj.get("from") or salary_obj.get("min")
            sal_to = salary_obj.get("to") or salary_obj.get("max")
            currency = salary_obj.get("currency", "PLN")
            period = salary_obj.get("type") or salary_obj.get("period") or "month"
            if sal_from or sal_to:
                parts = []
                if sal_from:
                    parts.append(str(sal_from))
                if sal_to:
                    parts.append(str(sal_to))
                salary_raw = f"{' - '.join(parts)} {currency}/{period}"
        elif salary_obj:
            salary_raw = str(salary_obj)

        # Employment type
        emp_type = raw.get("employmentType") or raw.get("employment_type") or None

        # Remote type
        remote = raw.get("remote") or raw.get("fullyRemote")
        if isinstance(remote, bool):
            remote_type_raw = "remote" if remote else None
        else:
            remote_type_raw = str(remote) if remote else None

        # Seniority in NoFluffJobs is usually a list
        seniority = raw.get("seniority") or raw.get("experienceLevel") or []
        if isinstance(seniority, list):
            seniority = ", ".join(str(s) for s in seniority)

        # Description
        description = raw.get("description") or raw.get("body") or ""
        if isinstance(description, dict):
            description = description.get("text") or description.get("html") or ""

        # Requirements / tech stack as additional description context
        requirements = raw.get("requirements") or raw.get("musts") or []
        if isinstance(requirements, list) and requirements:
            req_text = ", ".join(
                str(r.get("value") if isinstance(r, dict) else r) for r in requirements
            )
            if req_text:
                description = f"{description}\n\nRequired: {req_text}"

        url = raw.get("url") or raw.get("link") or ""
        if not url and job_id:
            url = f"https://nofluffjobs.com/job/{job_id}"

        return RawJob(
            platform="nofluffjobs",
            platform_job_id=str(job_id) if job_id else None,
            url=url,
            title=raw.get("title") or raw.get("name") or "",
            company=company or "",
            location=location,
            description=str(description),
            salary_raw=salary_raw,
            employment_type_raw=str(emp_type) if emp_type else None,
            remote_type_raw=remote_type_raw,
            posted_at_raw=raw.get("posted") or raw.get("createdAt") or None,
            raw=raw,
        )
