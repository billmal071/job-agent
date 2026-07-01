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


def test_prefilter_title_mismatch_skips_ai():
    mock_ai = MagicMock()
    matcher = JobMatcher(mock_ai)
    posting = _make_posting(title="Games Operation Specialist")
    profile = _make_profile()
    result = matcher.match(posting, profile)

    assert result.score == 0.0
    assert "title_mismatch" in result.red_flags
    assert not mock_ai.complete.called


def test_prefilter_title_match_passes():
    mock_ai = MagicMock()
    mock_ai.complete.return_value = '{"score": 0.8, "reasoning": "ok", "matched_skills": ["Python"], "missing_skills": [], "role_fit": "Good", "red_flags": []}'
    matcher = JobMatcher(mock_ai)
    posting = _make_posting(title="Senior Python Developer")
    profile = _make_profile()
    result = matcher.match(posting, profile)

    assert mock_ai.complete.called
    assert result.score == 0.8


def test_prefilter_no_skill_overlap_skips_ai():
    mock_ai = MagicMock()
    matcher = JobMatcher(mock_ai)
    posting = _make_posting(
        title="Software Developer",
        description="Looking for a Salesforce admin with Apex and SOQL experience.",
    )
    profile = _make_profile(
        search={"keywords": ["Software Developer"]},
    )
    result = matcher.match(posting, profile)

    assert result.score == 0.0
    assert "no_skill_overlap" in result.red_flags
    assert not mock_ai.complete.called


def test_prefilter_skill_overlap_passes():
    mock_ai = MagicMock()
    mock_ai.complete.return_value = '{"score": 0.7, "reasoning": "ok", "matched_skills": ["Python"], "missing_skills": [], "role_fit": "Decent", "red_flags": []}'
    matcher = JobMatcher(mock_ai)
    posting = _make_posting(
        title="Software Developer",
        description="We use Python and Django for our backend services.",
    )
    profile = _make_profile(
        search={"keywords": ["Software Developer"]},
    )
    result = matcher.match(posting, profile)

    assert mock_ai.complete.called
    assert result.score == 0.7


def test_prefilter_no_keywords_skips_title_check():
    mock_ai = MagicMock()
    mock_ai.complete.return_value = '{"score": 0.6, "reasoning": "ok", "matched_skills": [], "missing_skills": [], "role_fit": "Fair", "red_flags": []}'
    matcher = JobMatcher(mock_ai)
    posting = _make_posting(title="Totally Unrelated Role")
    profile = _make_profile(search={})
    result = matcher.match(posting, profile)

    assert mock_ai.complete.called


def test_match_calls_ai():
    mock_ai = MagicMock()
    mock_ai.complete.return_value = '{"score": 0.85, "reasoning": "Good match", "matched_skills": ["Python"], "missing_skills": [], "role_fit": "Strong", "red_flags": []}'

    matcher = JobMatcher(mock_ai)
    posting = _make_posting()
    profile = _make_profile()
    result = matcher.match(posting, profile)

    assert result.score == 0.85
    assert mock_ai.complete.called
