from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterator

from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source

logger = logging.getLogger(__name__)


class BaseFetcher(ABC):
    """
    Interface all fetchers must implement.

    Each fetcher is responsible for:
    - Connecting to / reading the source
    - Yielding RawFetchedItem objects (one per content piece)
    - NOT normalizing, NOT deduplicating, NOT saving to DB

    Fetchers should be stateless — source config is passed per-call.
    """

    #: Override in subclass with the fetch_method string this fetcher handles
    fetch_method: str = ""

    @abstractmethod
    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        """
        Yield raw fetched items from the source.
        Raise FetchError on unrecoverable failures.
        Log and skip on recoverable per-item errors.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} fetch_method={self.fetch_method!r}>"


class FetchError(Exception):
    """Raised when a fetcher fails in a way that should be recorded on the source."""
    pass
