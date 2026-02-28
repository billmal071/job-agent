"""Indeed job search and discovery."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, safe_text
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class IndeedDiscovery:
    """Handles Indeed job search, pagination, and detail extraction."""

    BASE_URL = "https://www.indeed.com/jobs"

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    def search(
        self,
        query: str,
        location: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        """Search Indeed for jobs."""
        params = {"q": query}
        if location:
            params["l"] = location

        url = f"{self.BASE_URL}?{urlencode(params)}"
        log.info("indeed_search", query=query, location=location)

        self.rate_limiter.wait()
        self.page.goto(url)
        self.page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        jobs: list[JobPosting] = []
        page_num = 0

        while len(jobs) < limit:
            new_jobs = self._extract_job_cards()
            if not new_jobs:
                break
            jobs.extend(new_jobs)
            self.rate_limiter.success()
            log.info("indeed_page_scraped", page=page_num, jobs_found=len(new_jobs))

            if len(jobs) >= limit:
                break
            if not self._next_page():
                break
            page_num += 1

        return jobs[:limit]

    def _extract_job_cards(self) -> list[JobPosting]:
        """Extract job cards from current page."""
        jobs: list[JobPosting] = []
        self.page.wait_for_selector(".job_seen_beacon, .resultContent", timeout=10000)
        human_delay(1000, 2000)

        cards = self.page.locator(".job_seen_beacon, .resultContent").all()
        for card in cards:
            try:
                title_el = card.locator("h2.jobTitle a, .jobTitle > a").first
                title = title_el.inner_text().strip() if title_el.count() > 0 else ""

                company_el = card.locator('[data-testid="company-name"], .companyName').first
                company = company_el.inner_text().strip() if company_el.count() > 0 else ""

                location_el = card.locator('[data-testid="text-location"], .companyLocation').first
                location = location_el.inner_text().strip() if location_el.count() > 0 else ""

                # Extract job URL and ID
                link_el = card.locator("h2.jobTitle a, .jobTitle > a").first
                url = ""
                external_id = ""
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
                    if href.startswith("/"):
                        url = f"https://www.indeed.com{href}"
                    else:
                        url = href
                    match = re.search(r"jk=([a-f0-9]+)", url)
                    if match:
                        external_id = match.group(1)

                if not external_id or not title:
                    continue

                salary_el = card.locator(".salary-snippet-container, .metadata.salary-snippet-container").first
                salary = salary_el.inner_text().strip() if salary_el.count() > 0 else None

                jobs.append(JobPosting(
                    external_id=external_id,
                    platform=Platform.INDEED,
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    salary=salary,
                    remote="remote" in location.lower(),
                ))
            except Exception as e:
                log.debug("indeed_card_error", error=str(e))

        return jobs

    def _next_page(self) -> bool:
        """Navigate to next page of results."""
        try:
            self.rate_limiter.wait()
            next_link = self.page.locator('a[data-testid="pagination-page-next"], a[aria-label="Next Page"]')
            if next_link.count() > 0:
                next_link.click()
                self.page.wait_for_load_state("networkidle")
                human_delay(2000, 4000)
                return True
        except Exception as e:
            log.debug("indeed_next_page_failed", error=str(e))
        return False

    def get_details(self, job_url: str) -> JobPosting:
        """Get full job details from Indeed."""
        self.rate_limiter.wait()
        self.page.goto(job_url)
        self.page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        title = safe_text(self.page,".jobsearch-JobInfoHeader-title, h1")
        company = safe_text(self.page,'[data-testid="inlineHeader-companyName"], .jobsearch-InlineCompanyRating-companyHeader')
        location = safe_text(self.page,'[data-testid="inlineHeader-companyLocation"], .jobsearch-InlineCompanyRating > div:last-child')
        description = safe_text(self.page,"#jobDescriptionText, .jobsearch-jobDescriptionText")

        match = re.search(r"jk=([a-f0-9]+)", job_url)
        external_id = match.group(1) if match else ""

        self.rate_limiter.success()
        return JobPosting(
            external_id=external_id,
            platform=Platform.INDEED,
            title=title,
            company=company,
            location=location,
            description=description,
            url=job_url,
            remote="remote" in location.lower(),
        )
