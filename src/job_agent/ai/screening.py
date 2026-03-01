"""AI-powered screening question answering for job applications."""

from __future__ import annotations

from dataclasses import dataclass, field

from job_agent.ai.client import AIClient
from job_agent.ai.prompts import SCREENING_ANSWER_TEMPLATE, SCREENING_CHOICE_TEMPLATE
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class FormField:
    """A single form field extracted from an application page."""

    label: str
    field_type: str  # text, select, radio, checkbox, textarea, number
    options: list[str] = field(default_factory=list)
    required: bool = False
    selector: str = ""
    current_value: str = ""


@dataclass
class FieldAnswer:
    """AI-generated answer for a form field."""

    label: str
    field_type: str
    answer: str


class ScreeningAnswerer:
    """Generates AI-powered answers for screening questions.

    Uses choice-aware prompts for select/radio fields and free-text
    prompts for text/textarea/number fields. Caches answers by label
    to avoid duplicate AI calls.
    """

    def __init__(
        self,
        ai_client: AIClient,
        candidate_summary: str,
        salary_expectation: str = "",
    ):
        self._ai = ai_client
        self._candidate_summary = candidate_summary
        self._salary_expectation = salary_expectation
        self._cache: dict[str, str] = {}

    def answer_field(self, field: FormField) -> FieldAnswer:
        """Generate an answer for a form field, using cache if available."""
        cache_key = field.label.strip().lower()

        if cache_key in self._cache:
            log.debug("screening_answer_cached", label=field.label)
            return FieldAnswer(
                label=field.label,
                field_type=field.field_type,
                answer=self._cache[cache_key],
            )

        if field.field_type in ("select", "radio") and field.options:
            answer = self._answer_choice(field)
        else:
            answer = self._answer_freetext(field)

        self._cache[cache_key] = answer

        log.info(
            "screening_answer_generated",
            label=field.label,
            field_type=field.field_type,
            answer=answer[:100],
        )

        return FieldAnswer(
            label=field.label,
            field_type=field.field_type,
            answer=answer,
        )

    def _answer_choice(self, field: FormField) -> str:
        """Answer a select/radio question by picking from available options."""
        prompt = SCREENING_CHOICE_TEMPLATE.render(
            question=field.label,
            options=field.options,
            candidate_summary=self._candidate_summary,
            salary_expectation=self._salary_expectation,
        )
        raw = self._ai.complete(
            prompt=prompt,
            temperature=0.1,
            max_tokens=128,
        ).strip()

        # Try to match the raw answer to one of the options
        for option in field.options:
            if raw.strip().lower() == option.strip().lower():
                return option

        # Fallback: check if the answer contains an option
        for option in field.options:
            if option.strip().lower() in raw.lower():
                return option

        # Last resort: return the first option if AI gave something unexpected
        log.warning(
            "screening_choice_no_match",
            label=field.label,
            ai_answer=raw,
            options=field.options,
        )
        return field.options[0] if field.options else raw

    def _answer_freetext(self, field: FormField) -> str:
        """Answer a free-text question."""
        prompt = SCREENING_ANSWER_TEMPLATE.render(
            question=field.label,
            candidate_summary=self._candidate_summary,
            salary_expectation=self._salary_expectation,
        )
        return self._ai.complete(
            prompt=prompt,
            temperature=0.2,
            max_tokens=256,
        ).strip()
