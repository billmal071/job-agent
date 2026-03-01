"""Score jobs against profiles using AI."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from job_agent.ai.client import AIClient
from job_agent.ai.prompts import JOB_MATCH_TEMPLATE
from job_agent.platforms.base import JobPosting
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class MatchScore:
    """Result of matching a job against a profile."""

    score: float
    reasoning: str = ""
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    role_fit: str = ""
    red_flags: list[str] = field(default_factory=list)


class JobMatcher:
    """Scores jobs against candidate profiles using AI."""

    def __init__(self, ai_client: AIClient):
        self.ai = ai_client

    def match(self, job: JobPosting, profile: dict[str, Any]) -> MatchScore:
        """Score a job posting against a candidate profile."""
        # Check exclusions first (no need to call AI)
        exclusions = profile.get("exclusions", {})
        excluded_companies = [c.lower() for c in exclusions.get("companies", [])]
        excluded_keywords = [k.lower() for k in exclusions.get("keywords", [])]

        if job.company.lower() in excluded_companies:
            return MatchScore(
                score=0.0,
                reasoning=f"Company '{job.company}' is in the exclusion list.",
                red_flags=["excluded_company"],
            )

        desc_lower = job.description.lower()
        for kw in excluded_keywords:
            if kw in desc_lower or kw in job.title.lower():
                return MatchScore(
                    score=0.0,
                    reasoning=f"Excluded keyword '{kw}' found in posting.",
                    red_flags=["excluded_keyword"],
                )

        # Build prompt
        skills = profile.get("skills", {})
        search = profile.get("search", {})

        prompt = JOB_MATCH_TEMPLATE.render(
            job_title=job.title,
            company=job.company,
            location=job.location,
            description=job.description[:6000],  # Truncate very long descriptions
            profile_name=profile.get("name", ""),
            required_skills=skills.get("required", []),
            preferred_skills=skills.get("preferred", []),
            experience_level=search.get("experience_level", ""),
            remote_preference=search.get("remote_preference", ""),
            salary_minimum=search.get("salary_minimum", "Not specified"),
            excluded_companies=exclusions.get("companies", []),
            excluded_keywords=exclusions.get("keywords", []),
        )

        try:
            response = self.ai.complete(
                prompt=prompt,
                system="You are a precise job matching AI. Always respond with valid JSON only.",
                temperature=0.2,
            )
            return self._parse_response(response)
        except Exception as e:
            log.error("match_failed", job_id=job.external_id, error=str(e))
            return MatchScore(
                score=0.5,
                reasoning=f"Matching failed: {e}",
                red_flags=["match_error"],
            )

    def _parse_response(self, response: str) -> MatchScore:
        """Parse the AI response into a MatchScore."""
        text = response.strip()

        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

        # Extract JSON object from surrounding text (Llama models sometimes wrap)
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            text = json_match.group()

        try:
            data = json.loads(text)

            # Type-validate and coerce
            score = data.get("score", 0.5)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.5
            score = max(0.0, min(1.0, score))

            matched = data.get("matched_skills", [])
            if not isinstance(matched, list):
                matched = []
            matched = [str(s) for s in matched]

            missing = data.get("missing_skills", [])
            if not isinstance(missing, list):
                missing = []
            missing = [str(s) for s in missing]

            flags = data.get("red_flags", [])
            if not isinstance(flags, list):
                flags = []
            flags = [str(f) for f in flags]

            return MatchScore(
                score=score,
                reasoning=str(data.get("reasoning", "")),
                matched_skills=matched,
                missing_skills=missing,
                role_fit=str(data.get("role_fit", "")),
                red_flags=flags,
            )
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("match_parse_error", error=str(e), response=text[:200])
            return MatchScore(
                score=0.5,
                reasoning=f"Failed to parse AI response: {e}",
                red_flags=["parse_error"],
            )
