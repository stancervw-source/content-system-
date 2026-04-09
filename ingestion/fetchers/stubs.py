from __future__ import annotations

from typing import Iterator

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source


class XApiFetcher(BaseFetcher):
    """
    Wave 3 — X (Twitter) API fetcher. NOT IMPLEMENTED.

    Requires X API v2 credentials and elevated access.
    Add TWITTER_BEARER_TOKEN to .env when implementing.

    TODO:
    - Use httpx to call GET /2/users/:id/tweets
    - Include expansions: author_id, referenced_tweets
    - Handle pagination with next_token
    - Respect rate limits (900 req / 15 min for bearer token)
    """

    fetch_method = "x_api"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        raise FetchError(
            f"x_api fetcher is not yet implemented (Wave 3). "
            f"Source {source.canonical_key!r} skipped."
        )


class LinkedInApiFetcher(BaseFetcher):
    """
    Wave 3 — LinkedIn API fetcher. NOT IMPLEMENTED.

    LinkedIn API has strict access controls.
    Requires LinkedIn Partner Program or scraping workaround.

    TODO:
    - Evaluate unofficial LinkedIn scraping approach (playwright-based)
    - Or monitor RSS of LinkedIn newsletters (some creators offer RSS)
    - Or manual import as fallback for top-tier LinkedIn sources
    """

    fetch_method = "linkedin_api"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        raise FetchError(
            f"linkedin_api fetcher is not yet implemented (Wave 3). "
            f"Source {source.canonical_key!r} skipped."
        )
