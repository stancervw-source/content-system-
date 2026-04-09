from __future__ import annotations

import logging
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ContentSystemBot/1.0)"
}


class WebScraperFetcher(BaseFetcher):
    """
    Wave 2 — Generic web page scraper.

    Fetches a single URL and extracts the main text content.
    No JS rendering — static HTML only.

    fetch_config keys:
      - urls: list of URLs to scrape (if source has multiple pages)
      - content_selector: CSS selector for main content area (default: auto)
      - title_selector: CSS selector for title (default: auto)
    """

    fetch_method = "web_scraper"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        urls: list[str] = source.fetch_config.get("urls", [])
        if not urls and source.url:
            urls = [source.url]

        if not urls:
            raise FetchError(f"Source {source.canonical_key!r} has no URLs to scrape")

        content_selector: str | None = source.fetch_config.get("content_selector")
        title_selector: str | None = source.fetch_config.get("title_selector")

        with httpx.Client(timeout=20, headers=DEFAULT_HEADERS, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    yield self._parse_page(resp.text, url, source, content_selector, title_selector)
                except httpx.HTTPError as exc:
                    logger.warning("HTTP error scraping %s: %s", url, exc)
                except Exception as exc:
                    logger.warning("Failed to scrape %s: %s", url, exc)

    @staticmethod
    def _parse_page(
        html: str,
        url: str,
        source: Source,
        content_selector: str | None,
        title_selector: str | None,
    ) -> RawFetchedItem:
        soup = BeautifulSoup(html, "lxml")

        # Title extraction
        title = None
        if title_selector:
            el = soup.select_one(title_selector)
            title = el.get_text(strip=True) if el else None
        if not title:
            og_title = soup.find("meta", property="og:title")
            title = og_title.get("content") if og_title else None
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        # Content extraction
        raw_text = ""
        if content_selector:
            el = soup.select_one(content_selector)
            raw_text = el.get_text(separator="\n", strip=True) if el else ""

        if not raw_text:
            # Auto: try common content containers
            for selector in ("article", "main", ".content", ".post-content", "#content"):
                el = soup.select_one(selector)
                if el:
                    raw_text = el.get_text(separator="\n", strip=True)
                    break

        if not raw_text:
            raw_text = soup.get_text(separator="\n", strip=True)

        return RawFetchedItem(
            source_id=source.id,
            external_content_id=url,
            source_content_type="web_page",
            title=title,
            raw_text=raw_text,
            url=url,
            author_name=None,
            published_at=None,
            raw_payload={"scraped_url": url},
        )


class SiteChangeMonitorFetcher(WebScraperFetcher):
    """
    Wave 2 — Site change monitor (e.g. for pricing pages, changelog pages).

    Extends WebScraperFetcher. The content hash will differ when page content changes,
    triggering a new item. Useful for Visualping-style monitoring without the external tool.

    fetch_config keys: same as WebScraperFetcher
    """

    fetch_method = "site_change_monitor"
