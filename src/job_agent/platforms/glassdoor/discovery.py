"""Glassdoor job search and discovery."""

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


class GlassdoorDiscovery:
    """Handles Glassdoor job search and detail extraction."""

    BASE_URL = "https://www.glassdoor.com/Job/jobs.htm"

    def __init__(self, page: Page, rate_limiter: RateLimiter):
        self.page = page
        self.rate_limiter = rate_limiter

    def _dismiss_one_tap(self) -> None:
        """Dismiss Google One Tap auth popup if present."""
        try:
            one_tap = self.page.locator('iframe[src*="accounts.google.com/gsi"], #credential_picker_container')
            if one_tap.count() > 0:
                self.page.evaluate("document.querySelector('#credential_picker_container')?.remove()")
                self.page.evaluate("document.querySelector('iframe[src*=\"accounts.google.com/gsi\"]')?.remove()")
        except Exception:
            pass

    def _safe_goto(self, url: str) -> None:
        """Navigate to URL, handling OAuth redirect interruptions and Cloudflare."""
        try:
            self._dismiss_one_tap()
            self.page.goto(url)
            self.page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            if "interrupted by another navigation" in str(e):
                log.warning("glassdoor_nav_interrupted", url=url)
                self.page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 3000)
                self._dismiss_one_tap()
                self.page.goto(url)
                self.page.wait_for_load_state("domcontentloaded")
            else:
                raise

        # Wait through Cloudflare challenge if present
        for _ in range(6):
            if "just a moment" in self.page.title().lower():
                log.warning("glassdoor_cloudflare_wait")
                human_delay(5000, 8000)
            else:
                break

    def search(
        self,
        query: str,
        location: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        """Search Glassdoor for jobs."""
        params = {"sc.keyword": query}
        if location:
            params["locT"] = "C"
            params["locKeyword"] = location

        url = f"{self.BASE_URL}?{urlencode(params)}"
        log.info("glassdoor_search", query=query, location=location)

        self.rate_limiter.wait()
        self._safe_goto(url)
        human_delay(2000, 4000)

        jobs: list[JobPosting] = []
        page_num = 0

        while len(jobs) < limit:
            new_jobs = self._extract_job_cards()
            if not new_jobs:
                break
            jobs.extend(new_jobs)
            self.rate_limiter.success()

            if len(jobs) >= limit:
                break
            if not self._next_page():
                break
            page_num += 1

        return jobs[:limit]

    def _extract_job_cards(self) -> list[JobPosting]:
        """Extract job listings from current page."""
        jobs: list[JobPosting] = []

        self.page.wait_for_selector(
            '[data-test="jobListing"], .react-job-listing',
            timeout=10000,
        )
        human_delay(1000, 2000)

        cards = self.page.locator('[data-test="jobListing"], .react-job-listing').all()
        for card in cards:
            try:
                title_el = card.locator('[data-test="job-title"], .job-title').first
                title = title_el.inner_text().strip() if title_el.count() > 0 else ""

                company_el = card.locator('[data-test="emp-name"], [class*="EmployerProfile_employerNameContainer"], .employer-name').first
                company = company_el.inner_text().strip() if company_el.count() > 0 else ""
                # Clean up company name (remove rating suffix like "3.8")
                import re as _re
                company = _re.sub(r'\s*\d+\.\d+\s*$', '', company).strip()

                location_el = card.locator('[data-test="emp-location"], .location').first
                location = location_el.inner_text().strip() if location_el.count() > 0 else ""

                link_el = card.locator("a[href*='/job-listing/'], a[data-test='job-title']").first
                url = ""
                external_id = ""
                if link_el.count() > 0:
                    href = link_el.get_attribute("href") or ""
                    url = href if href.startswith("http") else f"https://www.glassdoor.com{href}"
                    # Try jobListingId param first, then extract from URL path
                    match = re.search(r"jobListingId=(\d+)", url)
                    if match:
                        external_id = match.group(1)
                    else:
                        # New URL format: /job-listing/...-JV_IC1234_KO... or just slug
                        match = re.search(r"JV_(?:IC)?(\d+)", url)
                        if match:
                            external_id = match.group(1)
                        elif "/job-listing/" in url:
                            # Use URL slug as ID
                            slug = url.split("/job-listing/")[-1].split("?")[0]
                            external_id = slug or ""

                if not external_id or not title:
                    continue

                salary_el = card.locator('[data-test="detailSalary"], .salary-estimate').first
                salary = salary_el.inner_text().strip() if salary_el.count() > 0 else None

                # Check for Easy Apply badge
                easy_apply = card.locator(
                    '[data-test="applyButton"], '
                    ".easy-apply-badge, "
                    ":text('Easy Apply'), :text('Apply Now')"
                ).count() > 0

                jobs.append(JobPosting(
                    external_id=external_id,
                    platform=Platform.GLASSDOOR,
                    title=title,
                    company=company,
                    location=location,
                    url=url,
                    salary=salary,
                    easy_apply=easy_apply,
                    remote="remote" in location.lower(),
                ))
            except Exception as e:
                log.debug("glassdoor_card_error", error=str(e))

        return jobs

    def _next_page(self) -> bool:
        try:
            self.rate_limiter.wait()
            next_btn = self.page.locator('button[data-test="pagination-next"], a.nextButton')
            if next_btn.count() > 0 and next_btn.is_enabled():
                next_btn.click()
                self.page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
                return True
        except Exception:
            pass
        return False

    def get_details(self, job_url: str) -> JobPosting:
        """Get full job details."""
        self.rate_limiter.wait()
        self._safe_goto(job_url)
        human_delay(2000, 4000)

        title = safe_text(self.page,'[data-test="jobTitle"], .e1tk4kwz5')
        company = safe_text(self.page,'[data-test="employerName"], .e1tk4kwz4')
        location = safe_text(self.page,'[data-test="location"], .e1tk4kwz1')
        description = safe_text(self.page,'[data-test="jobDescriptionContent"], .jobDescriptionContent')

        match = re.search(r"jobListingId=(\d+)", job_url)
        external_id = match.group(1) if match else ""

        # Check for apply button on detail page
        easy_apply = self.page.locator(
            '[data-test="applyButton"], '
            'button:has-text("Apply"), '
            'a:has-text("Apply")'
        ).count() > 0

        self.rate_limiter.success()
        return JobPosting(
            external_id=external_id,
            platform=Platform.GLASSDOOR,
            title=title,
            company=company,
            location=location,
            description=description,
            url=job_url,
            easy_apply=easy_apply,
            remote="remote" in location.lower(),
        )
