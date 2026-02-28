"""Abstract base classes for platform drivers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol

from job_agent.db.models import Platform


@dataclass
class JobPosting:
    """Represents a discovered job posting."""

    external_id: str
    platform: Platform
    title: str
    company: str
    location: str = ""
    description: str = ""
    url: str = ""
    salary: str | None = None
    easy_apply: bool = False
    remote: bool = False
    extra: dict = field(default_factory=dict)


class PlatformDriver(ABC):
    """Abstract base class for job platform drivers."""

    platform: Platform

    @abstractmethod
    def login(self, username: str, password: str) -> None:
        """Authenticate with the platform."""

    @abstractmethod
    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        experience_level: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        """Search for jobs and return postings."""

    @abstractmethod
    def get_job_details(self, job_url: str) -> JobPosting:
        """Get full details for a specific job."""

    @abstractmethod
    def apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str = "",
        answers: dict[str, str] | None = None,
    ) -> bool:
        """Apply to a job. Returns True if successful."""

    @abstractmethod
    def is_already_applied(self, job: JobPosting) -> bool:
        """Check if already applied to this job."""

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""


class OutreachCapable(Protocol):
    """Mixin for platforms that support recruiter outreach."""

    def send_connection_request(
        self, profile_url: str, note: str = ""
    ) -> bool:
        """Send a connection request with an optional note."""
        ...

    def send_inmail(
        self, profile_url: str, subject: str, message: str
    ) -> bool:
        """Send an InMail message."""
        ...

    def search_people(
        self, company: str, title: str = "", limit: int = 10
    ) -> list[dict]:
        """Search for people (recruiters/hiring managers)."""
        ...
