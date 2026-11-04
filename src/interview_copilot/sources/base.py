"""Independent read-only source protocols; no mandatory all-purpose adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from ..jobs.model import JobRecord


class SourceError(Exception):
    """A safe reason, rather than an empty result pretending a fetch succeeded."""

    def __init__(
        self, reason: str, detail: str = "", *, retry_after: float | None = None
    ):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.retry_after = retry_after


@dataclass(frozen=True)
class JobRef:
    source_key: str
    external_id: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class SearchQuery:
    keywords: tuple[str, ...]
    cities: tuple[str, ...]
    any_city: bool
    conditions: tuple[Mapping, ...]
    request_id: str


@dataclass(frozen=True)
class JobPage:
    observations: tuple[JobRecord, ...]
    fetched_at: str
    next_cursor: str | None = None
    applied_filters: tuple[str, ...] = ()
    unsupported_filters: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccountContext:
    account_id: str
    source_key: str
    credential_ref: str | None = None


@dataclass(frozen=True)
class FeedbackPage:
    account_id: str
    items: tuple[Mapping, ...]
    fetched_at: str
    next_cursor: str | None = None


class SearchJobs(Protocol):
    def search_jobs(self, query: SearchQuery, cursor: str | None = None) -> JobPage: ...


class ReadJob(Protocol):
    def read_job(self, ref: JobRef) -> JobRecord: ...


class ReadFeedback(Protocol):
    def read_feedback(
        self, account: AccountContext, cursor: str | None = None
    ) -> FeedbackPage: ...
