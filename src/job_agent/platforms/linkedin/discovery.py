"""LinkedIn job search and discovery."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_click, human_delay, human_scroll
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, safe_text
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)

EXPERIENCE_LEVEL_MAP = {
    "entry": "2",
    "mid": "3",
    "senior": "4",
    "lead": "5",
    "director": "6",
    "executive": "7",
}


class LinkedInDiscovery:
    """Handles LinkedIn job search, pagination, and detail extraction."""

    BASE_URL = "https://www.linkedin.com/jobs/search/"

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    def search(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        experience_level: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        """Search LinkedIn for jobs matching criteria."""
        params: dict[str, str] = {"keywords": query}
        if location:
            params["location"] = location
        if remote:
            params["f_WT"] = "2"  # Remote filter
        if experience_level and experience_level.lower() in EXPERIENCE_LEVEL_MAP:
            params["f_E"] = EXPERIENCE_LEVEL_MAP[experience_level.lower()]

        url = f"{self.BASE_URL}?{urlencode(params)}"
        log.info("linkedin_search", query=query, location=location, url=url)

        self.rate_limiter.wait()
        self.page.goto(url, wait_until="domcontentloaded")
        human_delay(2000, 4000)

        jobs: list[JobPosting] = []
        page_num = 0

        while len(jobs) < limit:
            new_jobs = self._extract_job_cards()
            if not new_jobs:
                break

            jobs.extend(new_jobs)
            self.rate_limiter.success()
            log.info("linkedin_page_scraped", page=page_num, jobs_found=len(new_jobs))

            if len(jobs) >= limit:
                break

            # Try to go to next page
            if not self._next_page():
                break
            page_num += 1

        return jobs[:limit]

    def _extract_job_cards(self) -> list[JobPosting]:
        """Extract job postings from the current search results page."""
        jobs: list[JobPosting] = []

        # Wait for job cards to load
        self.page.wait_for_selector(
            ".jobs-search-results__list-item, .job-card-container",
            timeout=10000,
        )
        human_delay(1000, 2000)

        cards = self.page.locator(
            ".jobs-search-results__list-item, .job-card-container"
        ).all()

        for card in cards:
            try:
                job = self._parse_card(card)
                if job:
                    # Click card to load description in side panel
                    try:
                        card.click()
                        human_delay(1500, 2500)
                        desc_el = self.page.locator(
                            ".jobs-description__content, "
                            ".jobs-box__html-content, "
                            ".jobs-description-content__text"
                        ).first
                        if desc_el.count() > 0:
                            job.description = desc_el.inner_text().strip()
                    except Exception:
                        pass
                    jobs.append(job)
            except Exception as e:
                log.warning("linkedin_card_parse_error", error=str(e))
                continue

        return jobs

    def _parse_card(self, card) -> JobPosting | None:
        """Parse a single job card element into a JobPosting."""
        try:
            # Extract title
            title_el = card.locator(
                ".job-card-list__title, .job-card-container__link"
            ).first
            title = title_el.inner_text().strip() if title_el.count() > 0 else ""

            # Extract company
            company_el = card.locator(
                ".job-card-container__primary-description, "
                ".job-card-container__company-name"
            ).first
            company = company_el.inner_text().strip() if company_el.count() > 0 else ""

            # Extract location
            location_el = card.locator(
                ".job-card-container__metadata-item, "
                ".job-card-container__metadata-wrapper"
            ).first
            location = location_el.inner_text().strip() if location_el.count() > 0 else ""

            # Extract URL
            link_el = card.locator("a[href*='/jobs/view/']").first
            url = ""
            external_id = ""
            if link_el.count() > 0:
                href = link_el.get_attribute("href") or ""
                url = f"https://www.linkedin.com{href}" if href.startswith("/") else href
                # Extract job ID from URL
                match = re.search(r"/jobs/view/(\d+)", url)
                if match:
                    external_id = match.group(1)

            if not external_id or not title:
                return None

            # Check for Easy Apply badge (multiple selector strategies)
            easy_apply = (
                card.locator(
                    ".job-card-container__apply-method, "
                    "[data-is-easy-apply-button], "
                    ".jobs-apply-button--top-card, "
                    "li-icon[type='linkedin-bug']"
                ).count() > 0
                or "easy apply" in card.inner_text().lower()
            )

            # Check for remote
            remote = "remote" in location.lower()

            # Extract salary if visible
            salary = None
            salary_el = card.locator(".job-card-container__salary-info").first
            if salary_el.count() > 0:
                salary = salary_el.inner_text().strip()

            return JobPosting(
                external_id=external_id,
                platform=Platform.LINKEDIN,
                title=title,
                company=company,
                location=location,
                url=url,
                easy_apply=easy_apply,
                remote=remote,
                salary=salary,
            )
        except Exception as e:
            log.debug("linkedin_card_parse_failed", error=str(e))
            return None

    def _next_page(self) -> bool:
        """Navigate to the next page of results."""
        try:
            self.rate_limiter.wait()
            next_btn = self.page.locator(
                'button[aria-label="Next"], '
                'button.artdeco-pagination__button--next'
            )
            if next_btn.count() > 0 and next_btn.is_enabled():
                human_scroll(self.page, "down", 500)
                human_delay(500, 1000)
                human_click(self.page, 'button[aria-label="Next"]')
                self.page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
                return True
        except Exception as e:
            log.debug("linkedin_next_page_failed", error=str(e))
        return False

    def get_details(self, job_url: str) -> JobPosting:
        """Navigate to a job posting and extract full details."""
        self.rate_limiter.wait()
        self.page.goto(job_url, wait_until="domcontentloaded")
        human_delay(2000, 4000)

        title = safe_text(self.page,".t-24.job-details-jobs-unified-top-card__job-title, h1")
        company = safe_text(self.page,
            ".job-details-jobs-unified-top-card__company-name, "
            ".jobs-unified-top-card__company-name"
        )
        location = safe_text(self.page,
            ".job-details-jobs-unified-top-card__primary-description-container span, "
            ".jobs-unified-top-card__bullet"
        )

        # Get full description
        description = safe_text(self.page,
            ".jobs-description__content, "
            ".jobs-box__html-content"
        )

        # Extract job ID from URL
        match = re.search(r"/jobs/view/(\d+)", job_url)
        external_id = match.group(1) if match else ""

        # Check for Easy Apply (button text or badge)
        easy_apply = (
            self.page.locator(
                ".jobs-apply-button, "
                "[data-is-easy-apply-button], "
                "button:has-text('Easy Apply'), "
                ".jobs-apply-button--top-card"
            ).count() > 0
            or "easy apply" in (safe_text(self.page, ".jobs-apply-button") or "").lower()
        )

        salary = safe_text(self.page,
            ".job-details-jobs-unified-top-card__job-insight--highlight span"
        )

        self.rate_limiter.success()

        return JobPosting(
            external_id=external_id,
            platform=Platform.LINKEDIN,
            title=title,
            company=company,
            location=location,
            description=description,
            url=job_url,
            salary=salary or None,
            easy_apply=easy_apply,
            remote="remote" in location.lower(),
        )

    def is_already_applied(self, job_url: str) -> bool:
        """Check if already applied to a job by looking for the applied badge."""
        self.rate_limiter.wait()
        self.page.goto(job_url, wait_until="domcontentloaded")
        human_delay(1500, 3000)
        applied = self.page.locator(
            ".jobs-apply-button--applied, "
            '[aria-label*="Applied"]'
        ).count() > 0
        self.rate_limiter.success()
        return applied
