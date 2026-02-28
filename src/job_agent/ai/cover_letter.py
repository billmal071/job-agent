"""Generate cover letters using Claude API."""

from __future__ import annotations

from pathlib import Path

from job_agent.ai.client import AIClient
from job_agent.ai.prompts import COVER_LETTER_TEMPLATE
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class CoverLetterGenerator:
    """Generates tailored cover letters for job applications."""

    def __init__(self, ai_client: AIClient, settings: Settings):
        self.ai = ai_client
        self.settings = settings

    def generate(
        self,
        job: JobPosting,
        candidate_summary: str,
        matched_skills: list[str],
        tone: str | None = None,
    ) -> str:
        """Generate a cover letter for a specific job."""
        if tone is None:
            tone = self.settings.resume.cover_letter_tone

        prompt = COVER_LETTER_TEMPLATE.render(
            tone=tone,
            job_title=job.title,
            company=job.company,
            description=job.description,
            candidate_summary=candidate_summary,
            matched_skills=matched_skills,
        )

        cover_letter = self.ai.complete(
            prompt=prompt,
            system="You are a professional cover letter writer.",
            max_tokens=2048,
            temperature=0.4,
        )

        log.info("cover_letter_generated", job_id=job.external_id)
        return cover_letter

    def generate_and_save(
        self,
        job: JobPosting,
        candidate_summary: str,
        matched_skills: list[str],
        output_dir: str | None = None,
    ) -> str:
        """Generate cover letter and save as text file. Returns the file path."""
        if output_dir is None:
            output_dir = str(self.settings.data_dir / "cover_letters")

        text = self.generate(job, candidate_summary, matched_skills)
        safe_name = f"{job.company}_{job.external_id}".replace(" ", "_")[:60]

        out_path = Path(output_dir) / f"{safe_name}.txt"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text)

        log.info("cover_letter_saved", path=str(out_path))
        return str(out_path)
