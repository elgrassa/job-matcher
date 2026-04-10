"""Abstract scraper base class."""

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, ClassVar, Literal

from apify_client import ApifyClient
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from job_matcher.config import PlatformConfig
from job_matcher.models import RawJob

logger = logging.getLogger(__name__)

_ACTOR_RETRY = retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)


class ScraperError(Exception):
    pass


class ActorRunFailedError(ScraperError):
    pass


class Scraper(ABC):
    platform_name: ClassVar[Literal["linkedin", "justjoin", "nofluffjobs"]]

    def __init__(self, apify_token: str, config: PlatformConfig):
        self.client = ApifyClient(apify_token)
        self.config = config

    @abstractmethod
    def scrape(
        self,
        max_results: int | None = None,
        since: timedelta | None = None,
    ) -> Iterator[RawJob]:
        """Run actor(s), iterate results, yield RawJob instances."""

    @abstractmethod
    def parse_item(self, raw: dict[str, Any]) -> RawJob:
        """Convert a single actor dataset item into a RawJob."""

    @_ACTOR_RETRY
    def _run_actor(
        self,
        actor_id: str,
        run_input: dict[str, Any],
        timeout_secs: int = 300,
    ) -> str:
        """Run an Apify actor with retry + timeout, return the dataset ID."""
        logger.info("Running actor %s", actor_id)
        run = self.client.actor(actor_id).call(
            run_input=run_input,
            timeout_secs=timeout_secs,
        )
        if run is None or run.get("status") != "SUCCEEDED":
            raise ActorRunFailedError(f"Actor {actor_id} did not succeed: {run}")
        dataset_id: str = run["defaultDatasetId"]
        return dataset_id

    def _iterate_dataset(
        self, dataset_id: str, limit: int | None
    ) -> Iterator[dict[str, Any]]:
        """Iterate a dataset, optionally limiting total items."""
        for count, item in enumerate(self.client.dataset(dataset_id).iterate_items()):
            if limit is not None and count >= limit:
                break
            yield item
