"""Wellfound job search and discovery."""

from __future__ import annotations

import re
from urllib.parse import urlencode

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay, human_scroll
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, safe_goto, safe_text
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class WellfoundDiscovery:
    """Handles Wellfound job search with infinite scroll and detail extraction."""

    BASE_URL = "https://wellfound.com/jobs"

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    def search(
        self,
        query: str,
        location: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        """Search Wellfound for jobs."""
        params: dict[str, str] = {}
        if query:
            params["q"] = query
        if location:
            params["l"] = location

        url = f"{self.BASE_URL}?{urlencode(params)}" if params else self.BASE_URL
        log.info("wellfound_search", query=query, location=location)

        self.rate_limiter.wait()
        safe_goto(self.page, url)
        self.page.wait_for_selector(
            'div[data-test="StartupResult"], .styles_component__JobCard, .job-listing',
            timeout=15000,
        )
        human_delay(2000, 4000)

        jobs: list[JobPosting] = []
        max_scroll_attempts = 10

        for attempt in range(max_scroll_attempts):
            new_jobs = self._extract_job_cards()
            # Deduplicate against already collected jobs
            seen_ids = {j.external_id for j in jobs}
            for job in new_jobs:
                if job.external_id not in seen_ids:
                    jobs.append(job)
                    seen_ids.add(job.external_id)

            self.rate_limiter.success()
            log.info("wellfound_scroll_scraped", attempt=attempt, total_jobs=len(jobs))

            if len(jobs) >= limit:
                break
            if not self._load_more():
                break

        return jobs[:limit]

    def _extract_job_cards(self) -> list[JobPosting]:
        """Extract job cards from current page."""
        jobs: list[JobPosting] = []
        human_delay(500, 1000)

        cards = self.page.locator(
            'div[data-test="StartupResult"], .styles_component__JobCard, .job-listing'
        ).all()
        for card in cards:
            try:
                title_el = card.locator(
                    'a[data-test="job-title"], .job-title a, h4 a'
                ).first
                title = title_el.inner_text().strip() if title_el.count() > 0 else ""

                company_el = card.locator(
                    'a[data-test="startup-link"], .company-name, h2 a'
                ).first
                company = (
                    company_el.inner_text().strip() if company_el.count() > 0 else ""
                )

                location_el = card.locator(
                    '[data-test="job-location"], .location, .job-location'
                ).first
                location = (
                    location_el.inner_text().strip() if location_el.count() > 0 else ""
                )

                # Extract job URL and ID
                link_el = card.locator(
                    'a[data-test="job-title"], .job-title a, h4 a'
                ).first
                url = ""
                external_id = ""
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
                    if href.startswith("/"):
                        url = f"https://wellfound.com{href}"
                    else:
                        url = href
                    # Wellfound job IDs from URL path
                    match = re.search(r"/jobs/(\d+)", url)
                    if match:
                        external_id = match.group(1)
                    elif href:
                        external_id = href.rstrip("/").split("/")[-1]

                if not external_id or not title:
                    continue

                salary_el = card.locator(
                    '[data-test="compensation"], .salary, .compensation'
                ).first
                salary = (
                    salary_el.inner_text().strip() if salary_el.count() > 0 else None
                )

                jobs.append(
                    JobPosting(
                        external_id=external_id,
                        platform=Platform.WELLFOUND,
                        title=title,
                        company=company,
                        location=location,
                        url=url,
                        salary=salary,
                        easy_apply=True,  # Wellfound has built-in apply
                        remote="remote" in location.lower(),
                    )
                )
            except Exception as e:
                log.debug("wellfound_card_error", error=str(e))

        return jobs

    def _load_more(self) -> bool:
        """Scroll down to load more results (infinite scroll)."""
        try:
            self.rate_limiter.wait()
            # Count cards before scroll
            before_count = self.page.locator(
                'div[data-test="StartupResult"], .styles_component__JobCard, .job-listing'
            ).count()

            # Scroll to bottom using humanizer
            human_scroll(self.page, "down", 3000)
            human_delay(2000, 4000)

            # Wait and count cards after scroll
            after_count = self.page.locator(
                'div[data-test="StartupResult"], .styles_component__JobCard, .job-listing'
            ).count()

            if after_count > before_count:
                return True

            log.debug("wellfound_no_more_results")
        except Exception as e:
            log.debug("wellfound_scroll_failed", error=str(e))
        return False

    def get_details(self, job_url: str) -> JobPosting:
        """Get full job details from Wellfound."""
        self.rate_limiter.wait()
        safe_goto(self.page, job_url)
        self.page.wait_for_selector(
            '[data-test="job-description"], .job-description, .description',
            timeout=15000,
        )
        human_delay(2000, 4000)

        title = safe_text(self.page, 'h1[data-test="job-title"], h1.job-title, h1')
        company = safe_text(
            self.page, 'a[data-test="startup-link"], .company-name, h2 a'
        )
        location = safe_text(
            self.page, '[data-test="job-location"], .location, .job-location'
        )
        description = safe_text(
            self.page, '[data-test="job-description"], .job-description, .description'
        )

        match = re.search(r"/jobs/(\d+)", job_url)
        external_id = match.group(1) if match else job_url.rstrip("/").split("/")[-1]

        self.rate_limiter.success()
        return JobPosting(
            external_id=external_id,
            platform=Platform.WELLFOUND,
            title=title,
            company=company,
            location=location,
            description=description,
            url=job_url,
            easy_apply=True,
            remote="remote" in location.lower(),
        )
