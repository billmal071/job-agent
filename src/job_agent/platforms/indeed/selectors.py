"""Indeed-specific CSS selector registry."""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.platforms.selectors import PlatformSelectors


@dataclass(frozen=True)
class IndeedSelectors(PlatformSelectors):
    """CSS selectors for Indeed."""

    # -- Discovery: job card list --
    job_card: str = ".job_seen_beacon, .resultContent"
    job_title: str = "h2.jobTitle a, .jobTitle > a"
    job_company: str = '[data-testid="company-name"], .companyName'
    job_location: str = '[data-testid="text-location"], .companyLocation'
    job_url: str = "h2.jobTitle a, .jobTitle > a"
    job_salary: str = ".salary-snippet-container, .metadata.salary-snippet-container"
    easy_apply_badge: str = (
        ".iaLabel, .indeed-apply-badge, "
        "[data-indeed-apply-button], "
        ":text('Easily apply'), :text('Apply now')"
    )
    pagination_next: str = (
        'a[data-testid="pagination-page-next"], a[aria-label="Next Page"]'
    )

    # -- Discovery: job detail page --
    detail_title: str = ".jobsearch-JobInfoHeader-title, h1"
    detail_company: str = (
        '[data-testid="inlineHeader-companyName"], '
        ".jobsearch-InlineCompanyRating-companyHeader"
    )
    detail_location: str = (
        '[data-testid="inlineHeader-companyLocation"], '
        ".jobsearch-InlineCompanyRating > div:last-child"
    )
    detail_description: str = "#jobDescriptionText, .jobsearch-jobDescriptionText"
    detail_easy_apply: str = (
        "#indeedApplyButton, "
        'button[id*="apply"], '
        'a[href*="apply"], '
        ':text("Easily apply")'
    )

    # -- Applicator --
    apply_button: str = (
        '#indeedApplyButton, button[id*="apply"], button:has-text("Apply now")'
    )
    external_apply_link: str = (
        'a:has-text("Apply on company site"), '
        'a:has-text("Apply now"), '
        'a[href*="apply"], '
        'button:has-text("Apply on"), '
        "a.jobsearch-IndeedApplyButton-newDesign"
    )
    continue_button: str = (
        'button[id*="continue"], '
        'button:has-text("Continue"), '
        'button:has-text("Submit"), '
        'button:has-text("Apply")'
    )
    validation_errors: str = (
        ".ia-Questions-errorMessage, "
        '[role="alert"], '
        ".css-1s1r2hr"
    )

    # -- Indeed apply form field groups --
    field_group_question_item: str = ".ia-Questions-item"
    field_group_base_page: str = ".ia-BasePage-field"
    field_group_fieldset: str = "fieldset"
    field_group_testid: str = '[data-testid="questionItem"]'
    field_label: str = "label, legend, .ia-Questions-title"


SELECTORS = IndeedSelectors()
