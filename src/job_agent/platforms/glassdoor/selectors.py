"""Glassdoor-specific CSS selector registry."""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.platforms.selectors import PlatformSelectors


@dataclass(frozen=True)
class GlassdoorSelectors(PlatformSelectors):
    """CSS selectors for Glassdoor."""

    # -- Discovery: job card list --
    job_card: str = '[data-test="jobListing"], .react-job-listing'
    job_title: str = '[data-test="job-title"], .job-title'
    job_company: str = (
        '[data-test="emp-name"], '
        "[class*='EmployerProfile_employerNameContainer'], "
        ".employer-name"
    )
    job_location: str = '[data-test="emp-location"], .location'
    job_url: str = "a[href*='/job-listing/'], a[data-test='job-title']"
    job_salary: str = '[data-test="detailSalary"], .salary-estimate'
    easy_apply_badge: str = (
        '[data-test="applyButton"], '
        ".easy-apply-badge, "
        ":text('Easy Apply'), :text('Apply Now')"
    )
    pagination_next: str = 'button[data-test="pagination-next"], a.nextButton'

    # -- Discovery: job detail page --
    detail_title: str = '[data-test="jobTitle"], .e1tk4kwz5'
    detail_company: str = '[data-test="employerName"], .e1tk4kwz4'
    detail_location: str = '[data-test="location"], .e1tk4kwz1'
    detail_description: str = (
        '[data-test="jobDescriptionContent"], .jobDescriptionContent'
    )
    detail_easy_apply: str = (
        '[data-test="applyButton"], '
        'button:has-text("Apply"), '
        'a:has-text("Apply")'
    )

    # -- Applicator --
    apply_button: str = (
        '[data-test="applyButton"], button:has-text("Apply"), a:has-text("Apply")'
    )
    submit_button: str = 'button[type="submit"], button:has-text("Submit")'

    # -- Google One Tap auth popup --
    one_tap_iframe: str = (
        'iframe[src*="accounts.google.com/gsi"], #credential_picker_container'
    )


SELECTORS = GlassdoorSelectors()
