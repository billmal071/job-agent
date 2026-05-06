"""ZipRecruiter job search and discovery."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, safe_goto, safe_text
from job_agent.platforms.ziprecruiter.selectors import SELECTORS
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class ZipRecruiterDiscovery:
    """Handles ZipRecruiter job search, pagination, and detail extraction."""

    BASE_URL = "https://www.ziprecruiter.com/jobs-search"

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
        """Search ZipRecruiter for jobs."""
        params = {"search": query}
        if location:
            params["location"] = location
        if remote:
            params["remote"] = "1"
        if experience_level:
            params["search"] = f"{query} {experience_level}"

        url = f"{self.BASE_URL}?{urlencode(params)}"
        log.info("ziprecruiter_search", query=query, location=location)

        self.rate_limiter.wait()
        safe_goto(self.page, url)
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_selector(SELECTORS.job_card, timeout=10000)
        human_delay(2000, 4000)

        jobs: list[JobPosting] = []
        page_num = 0

        while len(jobs) < limit:
            new_jobs = self._extract_job_cards()
            if not new_jobs:
                break
            jobs.extend(new_jobs)
            self.rate_limiter.success()
            log.info(
                "ziprecruiter_page_scraped", page=page_num, jobs_found=len(new_jobs)
            )

            if len(jobs) >= limit:
                break
            if not self._next_page():
                break
            page_num += 1

        return jobs[:limit]

    def _extract_job_cards(self) -> list[JobPosting]:
        """Extract job cards from current page."""
        jobs: list[JobPosting] = []
        self.page.wait_for_selector(SELECTORS.job_card, timeout=10000)
        human_delay(1000, 2000)

        cards = self.page.locator(SELECTORS.job_card).all()
        for card in cards:
            try:
                title_el = card.locator(SELECTORS.job_title).first
                title = title_el.inner_text().strip() if title_el.count() > 0 else ""

                company_el = card.locator(SELECTORS.job_company).first
                company = (
                    company_el.inner_text().strip() if company_el.count() > 0 else ""
                )

                location_el = card.locator(SELECTORS.job_location).first
                location = (
                    location_el.inner_text().strip() if location_el.count() > 0 else ""
                )

                # Extract job URL and ID
                link_el = card.locator(SELECTORS.job_url).first
                url = ""
                external_id = ""
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
                    if href.startswith("/"):
                        url = f"https://www.ziprecruiter.com{href}"
                    else:
                        url = href
                    # ZipRecruiter job IDs are in the URL path
                    match = re.search(r"/jobs/.*?/([a-f0-9]+)", url)
                    if match:
                        external_id = match.group(1)
                    elif href:
                        # Fallback: use last path segment as ID
                        external_id = href.rstrip("/").split("/")[-1]

                if not external_id or not title:
                    continue

                salary_el = card.locator(SELECTORS.job_salary).first
                salary = (
                    salary_el.inner_text().strip() if salary_el.count() > 0 else None
                )

                # Check for 1-Click Apply badge
                easy_apply = card.locator(SELECTORS.easy_apply_badge).count() > 0

                jobs.append(
                    JobPosting(
                        external_id=external_id,
                        platform=Platform.ZIPRECRUITER,
                        title=title,
                        company=company,
                        location=location,
                        url=url,
                        salary=salary,
                        easy_apply=easy_apply,
                        remote="remote" in location.lower(),
                    )
                )
            except Exception as e:
                log.debug("ziprecruiter_card_error", error=str(e))

        return jobs

    def _next_page(self) -> bool:
        """Navigate to next page of results."""
        try:
            self.rate_limiter.wait()
            next_link = self.page.locator(SELECTORS.pagination_next)
            if next_link.count() > 0:
                next_link.click()
                self.page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
                return True
        except Exception as e:
            log.debug("ziprecruiter_next_page_failed", error=str(e))
        return False

    def get_details(self, job_url: str) -> JobPosting:
        """Get full job details from ZipRecruiter."""
        self.rate_limiter.wait()
        safe_goto(self.page, job_url)
        self.page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        title = safe_text(self.page, SELECTORS.detail_title)
        company = safe_text(self.page, SELECTORS.detail_company)
        location = safe_text(self.page, SELECTORS.detail_location)
        description = safe_text(self.page, SELECTORS.detail_description)

        # Extract ID from URL
        match = re.search(r"/jobs/.*?/([a-f0-9]+)", job_url)
        external_id = match.group(1) if match else job_url.rstrip("/").split("/")[-1]

        self.rate_limiter.success()
        return JobPosting(
            external_id=external_id,
            platform=Platform.ZIPRECRUITER,
            title=title,
            company=company,
            location=location,
            description=description,
            url=job_url,
            remote="remote" in location.lower(),
        )
