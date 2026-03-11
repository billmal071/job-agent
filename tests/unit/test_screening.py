"""Tests for ScreeningAnswerer."""

from __future__ import annotations

from unittest.mock import MagicMock

from job_agent.ai.screening import FieldAnswer, FormField, ScreeningAnswerer


def _make_answerer(
    ai_response: str = "some answer",
) -> tuple[ScreeningAnswerer, MagicMock]:
    ai = MagicMock()
    ai.complete.return_value = ai_response
    answerer = ScreeningAnswerer(
        ai_client=ai,
        candidate_summary="10 years Python experience",
        salary_expectation="$120,000",
    )
    return answerer, ai


class TestAnswerFreetextField:
    def test_answer_freetext_field(self):
        answerer, ai = _make_answerer("I have 10 years of experience.")

        field = FormField(label="Tell us about yourself", field_type="textarea")
        result = answerer.answer_field(field)

        ai.complete.assert_called_once()
        assert result.answer == "I have 10 years of experience."


class TestAnswerChoiceField:
    def test_answer_choice_field_exact_match(self):
        answerer, ai = _make_answerer("Yes")

        field = FormField(
            label="Are you authorized to work in the US?",
            field_type="select",
            options=["Yes", "No", "Requires Sponsorship"],
        )
        result = answerer.answer_field(field)

        assert result.answer == "Yes"
        ai.complete.assert_called_once()

    def test_answer_choice_field_contains_match(self):
        # AI returns text that contains one of the options
        answerer, ai = _make_answerer(
            "I would choose Full-Time since I prefer stability."
        )

        field = FormField(
            label="What is your preferred work type?",
            field_type="select",
            options=["Part-Time", "Full-Time", "Contract"],
        )
        result = answerer.answer_field(field)

        assert result.answer == "Full-Time"

    def test_answer_choice_field_no_match_fallback(self):
        # AI returns gibberish that matches no option — falls back to first
        answerer, ai = _make_answerer("xyzzy frobnicator")

        field = FormField(
            label="Years of experience?",
            field_type="radio",
            options=["0-2", "3-5", "6+"],
        )
        result = answerer.answer_field(field)

        assert result.answer == "0-2"


class TestCaching:
    def test_caching_same_label_no_second_ai_call(self):
        answerer, ai = _make_answerer("Yes")

        field = FormField(
            label="Are you authorized to work?",
            field_type="select",
            options=["Yes", "No"],
        )

        first = answerer.answer_field(field)
        second = answerer.answer_field(field)

        # AI should only be called once; second call served from cache
        assert ai.complete.call_count == 1
        assert first.answer == second.answer

    def test_caching_label_normalized(self):
        """Cache key is case-insensitive and strips whitespace."""
        answerer, ai = _make_answerer("Yes")

        field_lower = FormField(
            label="  are you authorized?  ",
            field_type="select",
            options=["Yes", "No"],
        )
        field_upper = FormField(
            label="ARE YOU AUTHORIZED?",
            field_type="select",
            options=["Yes", "No"],
        )

        answerer.answer_field(field_lower)
        answerer.answer_field(field_upper)

        assert ai.complete.call_count == 1


class TestAnswerFieldReturnsFieldAnswer:
    def test_returns_field_answer_dataclass(self):
        answerer, _ = _make_answerer("Python, Django, FastAPI")

        field = FormField(label="List your skills", field_type="text")
        result = answerer.answer_field(field)

        assert isinstance(result, FieldAnswer)
        assert result.label == "List your skills"
        assert result.field_type == "text"
        assert result.answer == "Python, Django, FastAPI"

    def test_choice_field_answer_preserves_metadata(self):
        answerer, _ = _make_answerer("No")

        field = FormField(
            label="Do you require sponsorship?",
            field_type="radio",
            options=["Yes", "No"],
        )
        result = answerer.answer_field(field)

        assert isinstance(result, FieldAnswer)
        assert result.label == "Do you require sponsorship?"
        assert result.field_type == "radio"
        assert result.answer == "No"
