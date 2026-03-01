"""Generate cold email drafts using AI."""

from __future__ import annotations

import json

from job_agent.ai.client import AIClient
from job_agent.ai.prompts import COLD_EMAIL_TEMPLATE
from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class ColdEmailGenerator:
    """Generates personalized cold emails for recruiter/hiring manager outreach."""

    def __init__(self, ai_client: AIClient, settings: Settings):
        self.ai = ai_client
        self.settings = settings

    def generate(
        self,
        job_title: str,
        company: str,
        recipient_name: str,
        recipient_title: str,
        matched_skills: list[str],
        candidate_summary: str,
    ) -> dict[str, str]:
        """Generate a cold email with subject and body.

        Returns dict with 'subject' and 'body' keys.
        """
        prompt = COLD_EMAIL_TEMPLATE.render(
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            company=company,
            job_title=job_title,
            matched_skills=matched_skills,
            candidate_summary=candidate_summary,
        )

        raw = self.ai.complete(
            prompt=prompt,
            system="You are a professional email writer specializing in job outreach.",
            max_tokens=1024,
            temperature=0.4,
        )

        # Parse JSON response with fallback
        try:
            result = json.loads(raw.strip())
            if isinstance(result, dict) and "subject" in result and "body" in result:
                log.info(
                    "cold_email_generated",
                    company=company,
                    recipient=recipient_name,
                )
                return {"subject": result["subject"], "body": result["body"]}
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: use raw text as body with generic subject
        log.warning("cold_email_json_fallback", company=company)
        return {
            "subject": f"Interest in {job_title} position at {company}",
            "body": raw.strip(),
        }
