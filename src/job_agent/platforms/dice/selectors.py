"""Dice-specific CSS selector registry."""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.platforms.selectors import PlatformSelectors


@dataclass(frozen=True)
class DiceSelectors(PlatformSelectors):
    """CSS selectors for Dice (uses web components and data-cy attributes)."""

    # -- Discovery: job card list --
    job_card: str = "dhi-search-card, [data-cy='search-card'], .search-card"
    job_title: str = "a.card-title-link, [data-cy='card-title'] a, .card-title a"
    job_company: str = (
        "a[data-cy='search-result-company-name'], .card-company a, .company-name"
    )
    job_location: str = (
        "[data-cy='search-result-location'], .card-location, .job-location"
    )
    job_url: str = "a.card-title-link, [data-cy='card-title'] a, .card-title a"
    job_salary: str = (
        "[data-cy='search-result-salary'], .card-salary, .compensation"
    )
    easy_apply_badge: str = (
        "[data-cy='easy-apply-badge'], .easy-apply-badge, :text('Easy Apply')"
    )
    pagination_next: str = (
        'a[aria-label="Next"], [data-cy="pagination-next"], li.pagination-next a'
    )

    # -- Discovery: job detail page --
    detail_title: str = (
        "h1[data-cy='jobTitle'], h1.job-title, [data-testid='jobTitle']"
    )
    detail_company: str = (
        "a[data-cy='companyNameLink'], .company-name, [data-testid='companyName']"
    )
    detail_location: str = (
        "[data-cy='locationDetails'], .job-location, [data-testid='location']"
    )
    detail_description: str = (
        "#jobDescription, [data-testid='jobDescription'], .job-description"
    )

    # -- Applicator --
    apply_button: str = (
        'button:has-text("Easy Apply"), '
        'button:has-text("Apply"), '
        'a[data-cy="apply-button"], '
        '[data-testid="apply-button"]'
    )
    submit_button: str = (
        'button:has-text("Submit"), '
        'button:has-text("Apply"), '
        'button:has-text("Next"), '
        'button[type="submit"]'
    )

    # -- Navigate to job (SPA wait selector) --
    detail_ready: str = (
        "#jobDescription, [data-testid='jobDescription'], .job-description"
    )


SELECTORS = DiceSelectors()
