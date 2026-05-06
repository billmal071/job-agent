"""Wellfound-specific CSS selector registry."""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.platforms.selectors import PlatformSelectors


@dataclass(frozen=True)
class WellfoundSelectors(PlatformSelectors):
    """CSS selectors for Wellfound (uses data-test attributes, infinite scroll)."""

    # -- Discovery: job card list (infinite scroll — no pagination_next) --
    job_card: str = (
        'div[data-test="StartupResult"], .styles_component__JobCard, .job-listing'
    )
    job_title: str = 'a[data-test="job-title"], .job-title a, h4 a'
    job_company: str = 'a[data-test="startup-link"], .company-name, h2 a'
    job_location: str = '[data-test="job-location"], .location, .job-location'
    job_url: str = 'a[data-test="job-title"], .job-title a, h4 a'
    job_salary: str = '[data-test="compensation"], .salary, .compensation'

    # -- Discovery: job detail page --
    detail_title: str = 'h1[data-test="job-title"], h1.job-title, h1'
    detail_company: str = 'a[data-test="startup-link"], .company-name, h2 a'
    detail_location: str = '[data-test="job-location"], .location, .job-location'
    detail_description: str = (
        '[data-test="job-description"], .job-description, .description'
    )

    # -- Navigate to job (wait selector) --
    detail_ready: str = (
        '[data-test="job-description"], .job-description, .description'
    )

    # -- Applicator --
    apply_button: str = (
        'button:has-text("Apply"), '
        'a:has-text("Apply Now"), '
        '[data-test="apply-button"]'
    )
    submit_button: str = (
        'button:has-text("Submit Application"), '
        'button:has-text("Submit"), '
        'button[type="submit"]'
    )
    cover_letter_textarea: str = (
        'textarea[name="coverLetter"], textarea[data-test="cover-letter"], textarea'
    )


SELECTORS = WellfoundSelectors()
