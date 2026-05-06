"""Base dataclass for platform-specific CSS selectors.

Each platform subclasses PlatformSelectors with its own selector strings.
Selectors use comma-separated values for fallback chains, which Playwright
handles natively.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSelectors:
    """Base selector registry for a job platform.

    Subclass this per platform and instantiate as a module-level SELECTORS
    singleton. Drivers import SELECTORS and use named fields instead of
    inline selector strings.

    All fields are CSS selector strings. Use comma-separated values for
    fallback chains (Playwright tries each in order).
    """

    # -- Discovery: job card list --
    job_card: str = ""
    job_title: str = ""
    job_company: str = ""
    job_location: str = ""
    job_url: str = ""
    job_salary: str = ""
    easy_apply_badge: str = ""
    pagination_next: str = ""

    # -- Discovery: job detail page --
    detail_title: str = ""
    detail_company: str = ""
    detail_location: str = ""
    detail_description: str = ""
    detail_easy_apply: str = ""
    detail_salary: str = ""

    # -- Applicator --
    apply_button: str = ""
    submit_button: str = ""
    applied_badge: str = ""
