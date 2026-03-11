"""Tests for job matcher."""

from unittest.mock import MagicMock

from job_agent.ai.job_matcher import JobMatcher
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting


def _make_posting(**kwargs) -> JobPosting:
    defaults = {
        "external_id": "123",
        "platform": Platform.LINKEDIN,
        "title": "Senior Python Developer",
        "company": "TechCo",
        "location": "Remote",
        "description": "We need a Python developer with Django, AWS, and PostgreSQL experience.",
    }
    defaults.update(kwargs)
    return JobPosting(**defaults)


def _make_profile(**kwargs) -> dict:
    defaults = {
        "name": "Python Dev",
        "search": {
            "keywords": ["Python Developer"],
            "experience_level": "senior",
            "remote_preference": "remote_first",
            "salary_minimum": 150000,
        },
        "skills": {
            "required": ["Python", "SQL"],
            "preferred": ["Django", "AWS"],
        },
        "exclusions": {
            "companies": ["BadCorp"],
            "keywords": ["unpaid"],
        },
    }
    defaults.update(kwargs)
    return defaults


def test_excluded_company():
    matcher = JobMatcher(MagicMock())
    posting = _make_posting(company="BadCorp")
    profile = _make_profile()
    result = matcher.match(posting, profile)
    assert result.score == 0.0
    assert "excluded_company" in result.red_flags


def test_excluded_keyword():
    matcher = JobMatcher(MagicMock())
    posting = _make_posting(description="This is an unpaid internship")
    profile = _make_profile()
    result = matcher.match(posting, profile)
    assert result.score == 0.0
    assert "excluded_keyword" in result.red_flags


def test_match_calls_ai():
    mock_ai = MagicMock()
    mock_ai.complete.return_value = '{"score": 0.85, "reasoning": "Good match", "matched_skills": ["Python"], "missing_skills": [], "role_fit": "Strong", "red_flags": []}'

    matcher = JobMatcher(mock_ai)
    posting = _make_posting()
    profile = _make_profile()
    result = matcher.match(posting, profile)

    assert result.score == 0.85
    assert mock_ai.complete.called
