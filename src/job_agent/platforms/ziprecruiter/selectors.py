"""ZipRecruiter-specific CSS selector registry."""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.platforms.selectors import PlatformSelectors


@dataclass(frozen=True)
class ZipRecruiterSelectors(PlatformSelectors):
    """CSS selectors for ZipRecruiter."""

    # -- Discovery: job card list --
    job_card: str = ".job_result_item, article.job_result, .job-listing"
    job_title: str = ".job_title a, h2.job_title, [data-testid='job-title'] a"
    job_company: str = ".company_name, a.company-name, [data-testid='company-name']"
    job_location: str = ".job_location, .location, [data-testid='job-location']"
    job_url: str = ".job_title a, h2.job_title a, [data-testid='job-title'] a"
    job_salary: str = ".salary, .compensation, [data-testid='salary']"
    easy_apply_badge: str = (
        ".one_click_apply, .quick-apply-badge, button:has-text('1-Click Apply')"
    )
    pagination_next: str = (
        'a[aria-label="Next"], a.next-page, [data-testid="pagination-next"]'
    )

    # -- Discovery: job detail page --
    detail_title: str = "h1.job-title, h1[data-testid='job-title'], .job_title h1"
    detail_company: str = (
        ".company-name, a[data-testid='company-name'], .hiring-company"
    )
    detail_location: str = ".location, [data-testid='job-location'], .job-location"
    detail_description: str = (
        ".job-description, [data-testid='job-description'], .jobDescriptionSection"
    )

    # -- Applicator --
    apply_button: str = (
        'button:has-text("1-Click Apply"), '
        'button:has-text("Apply"), '
        'a:has-text("Apply Now"), '
        '[data-testid="apply-button"]'
    )
    submit_button: str = (
        'button:has-text("Submit"), button:has-text("Apply"), button[type="submit"]'
    )


SELECTORS = ZipRecruiterSelectors()
