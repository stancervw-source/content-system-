from __future__ import annotations

import logging

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.fetchers.hackernews import HackerNewsFetcher
from ingestion.fetchers.manual_import import ManualImportFetcher
from ingestion.fetchers.rss import RSSFetcher
from ingestion.fetchers.stubs import LinkedInApiFetcher, XApiFetcher
from ingestion.fetchers.telegram import TelegramFetcher
from ingestion.fetchers.web_scraper import SiteChangeMonitorFetcher, WebScraperFetcher
from ingestion.fetchers.youtube import YouTubeFetcher

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, BaseFetcher] = {
    f.fetch_method: f
    for f in [
        RSSFetcher(),
        TelegramFetcher(),
        YouTubeFetcher(),
        HackerNewsFetcher(),
        WebScraperFetcher(),
        SiteChangeMonitorFetcher(),
        ManualImportFetcher(),
        XApiFetcher(),
        LinkedInApiFetcher(),
    ]
}


def get_fetcher(fetch_method: str) -> BaseFetcher:
    """Return the fetcher instance for the given fetch_method string."""
    fetcher = _REGISTRY.get(fetch_method)
    if not fetcher:
        raise FetchError(
            f"No fetcher registered for fetch_method={fetch_method!r}. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return fetcher
