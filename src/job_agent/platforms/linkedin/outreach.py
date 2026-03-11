"""LinkedIn recruiter outreach: connections, InMail, follow-ups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from playwright.sync_api import Page

from job_agent.ai.client import AIClient
from job_agent.ai.prompts import CONNECTION_NOTE_TEMPLATE
from job_agent.browser.humanizer import human_click, human_delay, human_type
from job_agent.db.models import OutreachStatus, Platform
from job_agent.db.repository import OutreachRepository
from job_agent.db.session import get_session
from job_agent.config import Settings
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class LinkedInOutreach:
    """Handles LinkedIn recruiter/hiring manager outreach."""

    def __init__(
        self,
        page: Page,
        rate_limiter: RateLimiter,
        settings: Settings,
        ai_client: AIClient,
    ):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings
        self.ai = ai_client

    def search_people(
        self,
        company: str,
        title: str = "recruiter",
        limit: int = 10,
    ) -> list[dict]:
        """Search for recruiters/hiring managers at a company."""
        self.rate_limiter.wait()

        query = f"{title} {company}"
        url = f"https://www.linkedin.com/search/results/people/?keywords={query}&origin=GLOBAL_SEARCH_HEADER"
        self.page.goto(url)
        self.page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        people: list[dict] = []
        cards = self.page.locator(".reusable-search__result-container").all()

        for card in cards[:limit]:
            try:
                name_el = card.locator(
                    ".entity-result__title-text a span[aria-hidden='true']"
                ).first
                name = name_el.inner_text().strip() if name_el.count() > 0 else ""

                title_el = card.locator(".entity-result__primary-subtitle").first
                person_title = (
                    title_el.inner_text().strip() if title_el.count() > 0 else ""
                )

                link_el = card.locator(".entity-result__title-text a").first
                profile_url = ""
                if link_el.count() > 0:
                    profile_url = link_el.get_attribute("href") or ""

                if name and profile_url:
                    people.append(
                        {
                            "name": name,
                            "title": person_title,
                            "company": company,
                            "profile_url": profile_url,
                        }
                    )
            except Exception as e:
                log.debug("people_parse_error", error=str(e))

        self.rate_limiter.success()
        log.info("people_search_complete", company=company, found=len(people))
        return people

    def send_connection_request(
        self,
        profile_url: str,
        recipient_name: str,
        recipient_title: str,
        company: str,
        job_title: str = "",
        related_job_id: int | None = None,
    ) -> bool:
        """Send a personalized connection request."""
        session = get_session(self.settings)
        outreach_repo = OutreachRepository(session)

        try:
            # Dedup check
            if outreach_repo.exists_for_recipient(profile_url):
                log.info("outreach_already_sent", recipient=recipient_name)
                return False

            # Check daily limit
            daily_count = outreach_repo.count_today(Platform.LINKEDIN)
            max_per_day = self.settings.platforms.linkedin.max_connections_per_day
            if daily_count >= max_per_day:
                log.warning(
                    "connection_daily_limit", count=daily_count, max=max_per_day
                )
                return False

            # Generate personalized note
            note = self._generate_connection_note(
                recipient_name, recipient_title, company, job_title
            )

            # Navigate to profile
            self.rate_limiter.wait()
            self.page.goto(profile_url)
            self.page.wait_for_load_state("domcontentloaded")
            human_delay(2000, 4000)

            # Click Connect button
            connect_btn = self.page.locator(
                'button[aria-label*="Connect"], button:has-text("Connect")'
            ).first
            if connect_btn.count() == 0:
                # Try the More menu
                more_btn = self.page.locator('button[aria-label="More actions"]').first
                if more_btn.count() > 0:
                    human_click(self.page, 'button[aria-label="More actions"]')
                    human_delay(500, 1000)
                    connect_option = self.page.locator(
                        'div[aria-label*="Connect"]'
                    ).first
                    if connect_option.count() == 0:
                        log.warning("no_connect_button", profile=profile_url)
                        return False
                    connect_option.click()
                else:
                    log.warning("no_connect_button", profile=profile_url)
                    return False
            else:
                connect_btn.click()

            human_delay(1000, 2000)

            # Click "Add a note"
            add_note_btn = self.page.locator('button[aria-label="Add a note"]').first
            if add_note_btn.count() > 0:
                add_note_btn.click()
                human_delay(500, 1000)

                # Type the note
                note_field = self.page.locator(
                    'textarea[name="message"], textarea#custom-message'
                ).first
                if note_field.count() > 0:
                    human_type(self.page, 'textarea[name="message"]', note[:300])

            # Click Send
            send_btn = self.page.locator(
                'button[aria-label="Send invitation"], button[aria-label="Send now"]'
            ).first
            if send_btn.count() > 0:
                send_btn.click()
                human_delay(1000, 2000)

            # Record in DB
            outreach_repo.create(
                platform=Platform.LINKEDIN,
                recipient_name=recipient_name,
                recipient_title=recipient_title,
                recipient_company=company,
                recipient_profile_url=profile_url,
                message_type="connection",
                message_text=note,
                status=OutreachStatus.SENT,
                related_job_id=related_job_id,
                sent_at=datetime.now(timezone.utc),
                follow_up_at=datetime.now(timezone.utc) + timedelta(days=4),
            )
            session.commit()

            self.rate_limiter.success()
            log.info("connection_sent", recipient=recipient_name, company=company)
            return True

        except Exception as e:
            session.rollback()
            self.rate_limiter.failure()
            log.error("connection_failed", recipient=recipient_name, error=str(e))
            return False
        finally:
            session.close()

    def send_inmail(
        self,
        profile_url: str,
        recipient_name: str,
        subject: str,
        message: str,
        related_job_id: int | None = None,
    ) -> bool:
        """Send an InMail message (requires LinkedIn Premium)."""
        session = get_session(self.settings)
        outreach_repo = OutreachRepository(session)

        try:
            if outreach_repo.exists_for_recipient(profile_url):
                return False

            self.rate_limiter.wait()
            self.page.goto(profile_url)
            self.page.wait_for_load_state("domcontentloaded")
            human_delay(2000, 4000)

            # Click Message button
            msg_btn = self.page.locator(
                'button[aria-label*="Message"], a[href*="messaging"]'
            ).first
            if msg_btn.count() == 0:
                log.warning("no_message_button", profile=profile_url)
                return False

            msg_btn.click()
            human_delay(1500, 3000)

            # Type subject if InMail form
            subject_field = self.page.locator('input[name="subject"]').first
            if subject_field.count() > 0:
                human_type(self.page, 'input[name="subject"]', subject)

            # Type message
            msg_field = self.page.locator(
                '.msg-form__contenteditable, div[role="textbox"]'
            ).first
            if msg_field.count() > 0:
                msg_field.click()
                human_delay(300, 600)
                self.page.keyboard.type(message, delay=80)

            # Send
            send_btn = self.page.locator(
                'button.msg-form__send-button, button[type="submit"]'
            ).first
            if send_btn.count() > 0:
                send_btn.click()
                human_delay(1000, 2000)

            outreach_repo.create(
                platform=Platform.LINKEDIN,
                recipient_name=recipient_name,
                recipient_profile_url=profile_url,
                message_type="inmail",
                message_text=message,
                status=OutreachStatus.SENT,
                related_job_id=related_job_id,
                sent_at=datetime.now(timezone.utc),
            )
            session.commit()

            self.rate_limiter.success()
            log.info("inmail_sent", recipient=recipient_name)
            return True

        except Exception as e:
            session.rollback()
            self.rate_limiter.failure()
            log.error("inmail_failed", error=str(e))
            return False
        finally:
            session.close()

    def _generate_connection_note(
        self,
        recipient_name: str,
        recipient_title: str,
        company: str,
        job_title: str,
    ) -> str:
        """Generate a personalized connection note using AI."""
        prompt = CONNECTION_NOTE_TEMPLATE.render(
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            company=company,
            job_title=job_title or "software engineering",
        )
        note = self.ai.complete(
            prompt=prompt,
            system="You write brief, genuine LinkedIn connection notes.",
            max_tokens=200,
            temperature=0.6,
        )
        return note.strip()[:300]
