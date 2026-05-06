"""LinkedIn-specific CSS selector registry.

All LinkedIn selectors are centralised here. Drivers import the SELECTORS
singleton and use named fields instead of inline strings, making it easy to
update when LinkedIn changes its HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

from job_agent.platforms.selectors import PlatformSelectors


@dataclass(frozen=True)
class LinkedInSelectors(PlatformSelectors):
    """CSS selectors for LinkedIn job search and Easy Apply flows."""

    # -- Discovery: job card list --
    job_card: str = (
        ".scaffold-layout__list-item, "
        ".jobs-search-results-list__list-item, "
        ".jobs-search-results__list-item, "
        ".job-card-container"
    )
    job_title: str = (
        ".job-card-list__title, "
        ".job-card-container__link, "
        ".artdeco-entity-lockup__title"
    )
    job_company: str = (
        ".job-card-container__primary-description, "
        ".job-card-container__company-name, "
        ".artdeco-entity-lockup__subtitle"
    )
    job_location: str = (
        ".job-card-container__metadata-item, "
        ".job-card-container__metadata-wrapper, "
        ".artdeco-entity-lockup__caption"
    )
    job_url: str = "a[href*='/jobs/view/']"
    job_salary: str = (
        ".job-card-container__salary-info, .artdeco-entity-lockup__metadata"
    )
    easy_apply_badge: str = (
        ".job-card-container__apply-method, "
        "[data-is-easy-apply-button], "
        ".jobs-apply-button--top-card, "
        "li-icon[type='linkedin-bug'], "
        ".job-card-container__footer-item--highlighted"
    )
    pagination_next: str = (
        'button[aria-label="Next"], '
        "button.artdeco-pagination__button--next, "
        'button[aria-label="View next page"]'
    )

    # -- Discovery: job detail page --
    detail_title: str = (
        ".t-24.job-details-jobs-unified-top-card__job-title, "
        ".job-details-jobs-unified-top-card__job-title, "
        ".jobs-unified-top-card__job-title, "
        "h1.t-24, "
        "h1"
    )
    detail_company: str = (
        ".job-details-jobs-unified-top-card__company-name, "
        ".jobs-unified-top-card__company-name, "
        ".artdeco-entity-lockup__subtitle"
    )
    detail_location: str = (
        ".job-details-jobs-unified-top-card__primary-description-container span, "
        ".jobs-unified-top-card__bullet, "
        ".artdeco-entity-lockup__caption"
    )
    detail_description: str = (
        ".jobs-description__content, "
        ".jobs-box__html-content, "
        ".jobs-description-content__text, "
        ".jobs-description, "
        "#job-details"
    )
    detail_easy_apply: str = (
        ".jobs-apply-button, "
        "[data-is-easy-apply-button], "
        "button:has-text('Easy Apply'), "
        "a:has-text('Easy Apply'), "
        ".jobs-apply-button--top-card, "
        ".jobs-s-apply button"
    )
    detail_salary: str = (
        ".job-details-jobs-unified-top-card__job-insight--highlight span, "
        ".salary-main-rail__data-body, "
        ".job-details-preferences-and-skills .t-14"
    )

    # -- Applicator: apply button --
    apply_button: str = ".jobs-apply-button"
    submit_button: str = (
        '[aria-label="Submit application"], '
        '[aria-label="Review your application"], '
        'button:has-text("Submit application"), '
        'button:has-text("Submit")'
    )
    applied_badge: str = (
        ".jobs-apply-button--applied, "
        '[aria-label*="Applied"], '
        ':text("Applied"), '
        ".artdeco-inline-feedback--success"
    )

    # -- Applicator: Easy Apply modal --
    easy_apply_modal: str = (
        ".jobs-easy-apply-modal, "
        '[data-test-modal-id="easy-apply-modal"], '
        '[role="dialog"]'
    )
    next_step_button: str = (
        '[aria-label="Continue to next step"], '
        '[aria-label="Next"], '
        'button:has-text("Next"), '
        'button:has-text("Continue")'
    )
    submit_application: str = (
        '[aria-label="Submit application"], '
        'button:has-text("Submit application"), '
        'button:has-text("Submit")'
    )
    review_application: str = (
        '[aria-label="Submit application"], '
        '[aria-label="Review your application"], '
        'button:has-text("Submit application"), '
        'button:has-text("Submit")'
    )

    # -- Applicator: login / session --
    login_popup: str = (
        '[data-test-modal-id="join-now-modal"], '
        ".join-now-modal, "
        '[role="dialog"]:has-text("Sign in"), '
        '[role="dialog"]:has-text("Join LinkedIn")'
    )
    login_popup_close: str = (
        'button[aria-label="Dismiss"], '
        'button[aria-label="Close"], '
        'button:has-text("✕"), '
        ".artdeco-modal__dismiss"
    )
    logged_in_indicators: str = (
        ".global-nav__me, nav[aria-label=\"Primary\"], .feed-identity-module"
    )
    login_indicators: str = (
        'a[href*="/login"], '
        'button:has-text("Sign in"), '
        '.nav__button-secondary:has-text("Sign in")'
    )

    # -- Applicator: discard dialog --
    discard_dialog: str = (
        '[data-test-modal-id="data-test-easy-apply-discard-confirmation"], '
        '[role="alertdialog"], '
        '[role="dialog"]:has-text("Discard")'
    )
    discard_button: str = (
        'button:has-text("Discard"), button[data-test-dialog-primary-btn]'
    )

    # -- Applicator: success / errors --
    success_confirmation: str = (
        ':text("Application sent"), '
        ':text("Your application was sent"), '
        ".artdeco-inline-feedback--success, "
        '[data-test-modal-id="post-apply-modal"]'
    )
    form_errors: str = (
        ".artdeco-inline-feedback--error, "
        ".fb-dash-form-element__error-field, "
        "[data-test-form-element-error], "
        ".jobs-easy-apply-form-element__error"
    )

    # -- Applicator: resume / cover letter upload --
    resume_uploaded: str = (
        ".jobs-document-upload-redesign-card__file-name, "
        ".jobs-document-upload__file-name, "
        ".jobs-resume-upload__file-name"
    )
    cover_letter_section: str = 'text="Cover letter", text="cover letter"'

    # -- Applicator: external apply link --
    external_apply_link: str = (
        'a:has-text("Apply"), a.jobs-apply-button, a[href*="/applyredirect"]'
    )

    # -- Applicator: screening questions --
    question_groups: str = (
        ".jobs-easy-apply-form-section__grouping, "
        ".jobs-easy-apply-form-element, "
        ".fb-dash-form-element"
    )
    question_label: str = "label, legend, span.t-14"

    # -- Applicator: contact fields --
    contact_fields: str = 'input[name="phone"], input[name="email"]'


SELECTORS = LinkedInSelectors()
