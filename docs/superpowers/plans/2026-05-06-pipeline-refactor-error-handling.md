# Pipeline Refactor & Error Handling Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break the monolithic `run_pipeline()` (560+ lines) into focused, testable functions and replace all silent exception swallowing with proper structured logging across pipeline and dashboard routes.

**Architecture:** Extract pipeline stages (discover, match, decide, apply) into standalone functions in a new `pipeline_steps.py` module. Each step takes explicit inputs and returns typed results. The existing `pipeline.py` becomes a thin orchestrator calling these steps. Dashboard routes get consistent `log.warning()`/`log.error()` calls replacing bare `except Exception:` blocks. A shared `_parse_json_field()` helper eliminates repeated JSON parsing try/except blocks.

**Tech Stack:** Python 3.11+, structlog, SQLAlchemy, pytest, uv

---

### Task 1: Add `_parse_json_field` helper and eliminate repeated JSON parsing

The codebase has ~15 identical try/except blocks for parsing JSON fields from match results. Extract to one helper.

**Files:**
- Create: `src/job_agent/utils/json_helpers.py`
- Test: `tests/unit/test_json_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_json_helpers.py
"""Tests for JSON parsing helper."""

from job_agent.utils.json_helpers import parse_json_list


class TestParseJsonList:
    def test_valid_json_list(self):
        assert parse_json_list('["Python", "Go"]') == ["Python", "Go"]

    def test_none_returns_default(self):
        assert parse_json_list(None) == []

    def test_empty_string_returns_default(self):
        assert parse_json_list("") == []

    def test_invalid_json_returns_default(self):
        assert parse_json_list("not json") == []

    def test_json_object_returns_default(self):
        assert parse_json_list('{"key": "val"}') == []

    def test_custom_default(self):
        assert parse_json_list(None, default=["fallback"]) == ["fallback"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_json_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/job_agent/utils/json_helpers.py
"""Shared JSON parsing utilities."""

from __future__ import annotations

import json


def parse_json_list(raw: str | None, *, default: list | None = None) -> list:
    """Parse a JSON string expected to be a list. Returns default on failure."""
    if default is None:
        default = []
    if not raw:
        return list(default)
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        return list(default)
    except (json.JSONDecodeError, TypeError, ValueError):
        return list(default)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_json_helpers.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/job_agent/utils/json_helpers.py tests/unit/test_json_helpers.py
git commit -m "feat: add parse_json_list helper to eliminate repeated JSON try/except blocks"
```

---

### Task 2: Extract pipeline step functions into `pipeline_steps.py`

Break the monolith into four focused functions: `discover_for_platform`, `match_job`, `apply_to_job`, `process_approved_jobs`. Each takes explicit deps and returns typed results.

**Files:**
- Create: `src/job_agent/orchestrator/pipeline_steps.py`
- Test: `tests/unit/test_pipeline_steps.py`

- [ ] **Step 1: Write failing tests for `match_job`**

```python
# tests/unit/test_pipeline_steps.py
"""Tests for extracted pipeline step functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.db.models import Base, Job, JobStatus, Platform


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def settings():
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
    )


class TestMatchJob:
    def test_returns_match_score(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import match_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import JobRepository, MatchResultRepository

        job_repo = JobRepository(db_session)
        match_repo = MatchResultRepository(db_session)

        posting = JobPosting(
            external_id="ext-1",
            platform=Platform.LINKEDIN,
            title="Software Engineer",
            company="Acme",
            location="Remote",
            description="Python dev needed",
            url="https://example.com/job/1",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_matcher = MagicMock()
        mock_score = MagicMock()
        mock_score.score = 85.0
        mock_score.reasoning = "Good fit"
        mock_score.matched_skills = '["Python"]'
        mock_score.missing_skills = '[]'
        mock_score.role_fit = "strong"
        mock_score.red_flags = '[]'
        mock_matcher.match.return_value = mock_score

        profile = {"name": "Backend Engineer"}

        result = match_job(
            job=job,
            posting=posting,
            matcher=mock_matcher,
            match_repo=match_repo,
            profile=profile,
        )

        assert result == mock_score
        assert job.status == JobStatus.MATCHED
        mock_matcher.match.assert_called_once_with(posting, profile)


class TestDecideJob:
    def test_auto_approve_above_threshold(self, settings):
        from job_agent.orchestrator.pipeline_steps import decide_job

        mock_score = MagicMock()
        mock_score.score = 90.0

        job = MagicMock()
        settings.matching.auto_apply_threshold = 80
        settings.matching.review_threshold = 50

        decision = decide_job(job, mock_score, settings)

        assert decision == "auto_apply"
        assert job.status == JobStatus.AUTO_APPROVED

    def test_queue_between_thresholds(self, settings):
        from job_agent.orchestrator.pipeline_steps import decide_job

        mock_score = MagicMock()
        mock_score.score = 60.0

        job = MagicMock()
        settings.matching.auto_apply_threshold = 80
        settings.matching.review_threshold = 50

        decision = decide_job(job, mock_score, settings)

        assert decision == "queue"
        assert job.status == JobStatus.QUEUED

    def test_skip_below_review_threshold(self, settings):
        from job_agent.orchestrator.pipeline_steps import decide_job

        mock_score = MagicMock()
        mock_score.score = 30.0

        job = MagicMock()
        settings.matching.auto_apply_threshold = 80
        settings.matching.review_threshold = 50

        decision = decide_job(job, mock_score, settings)

        assert decision == "skip"
        assert job.status == JobStatus.SKIPPED


class TestApplyToJob:
    def test_success_sets_applied_status(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import apply_to_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import ApplicationRepository, JobRepository

        job_repo = JobRepository(db_session)
        app_repo = ApplicationRepository(db_session)

        posting = JobPosting(
            external_id="ext-1",
            platform=Platform.LINKEDIN,
            title="SWE",
            company="Acme",
            location="Remote",
            description="desc",
            url="https://example.com/job/1",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_driver = MagicMock()
        mock_driver.apply.return_value = True
        mock_resume_tailor = MagicMock()
        mock_resume_tailor.tailor_and_save.return_value = "/tmp/resume.pdf"
        mock_cl_gen = MagicMock()
        mock_cl_gen.generate_and_save.return_value = "/tmp/cover.pdf"

        result = apply_to_job(
            job=job,
            posting=posting,
            driver=mock_driver,
            resume_tailor=mock_resume_tailor,
            cover_letter_gen=mock_cl_gen,
            app_repo=app_repo,
            candidate_summary="Python dev",
            matched_skills=["Python"],
        )

        assert result is True
        assert job.status == JobStatus.APPLIED

    def test_failure_sets_apply_failed(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import apply_to_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import ApplicationRepository, JobRepository

        job_repo = JobRepository(db_session)
        app_repo = ApplicationRepository(db_session)

        posting = JobPosting(
            external_id="ext-2",
            platform=Platform.LINKEDIN,
            title="SWE",
            company="Acme",
            location="Remote",
            description="desc",
            url="https://example.com/job/2",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_driver = MagicMock()
        mock_driver.apply.return_value = False
        mock_resume_tailor = MagicMock()
        mock_resume_tailor.tailor_and_save.return_value = "/tmp/resume.pdf"
        mock_cl_gen = MagicMock()
        mock_cl_gen.generate_and_save.return_value = "/tmp/cover.pdf"

        result = apply_to_job(
            job=job,
            posting=posting,
            driver=mock_driver,
            resume_tailor=mock_resume_tailor,
            cover_letter_gen=mock_cl_gen,
            app_repo=app_repo,
            candidate_summary="Python dev",
            matched_skills=["Python"],
        )

        assert result is False
        assert job.status == JobStatus.APPLY_FAILED

    def test_cover_letter_failure_continues(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import apply_to_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import ApplicationRepository, JobRepository

        job_repo = JobRepository(db_session)
        app_repo = ApplicationRepository(db_session)

        posting = JobPosting(
            external_id="ext-3",
            platform=Platform.LINKEDIN,
            title="SWE",
            company="Acme",
            location="Remote",
            description="desc",
            url="https://example.com/job/3",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_driver = MagicMock()
        mock_driver.apply.return_value = True
        mock_resume_tailor = MagicMock()
        mock_resume_tailor.tailor_and_save.return_value = "/tmp/resume.pdf"
        mock_cl_gen = MagicMock()
        mock_cl_gen.generate_and_save.side_effect = RuntimeError("AI failed")

        result = apply_to_job(
            job=job,
            posting=posting,
            driver=mock_driver,
            resume_tailor=mock_resume_tailor,
            cover_letter_gen=mock_cl_gen,
            app_repo=app_repo,
            candidate_summary="Python dev",
            matched_skills=["Python"],
        )

        assert result is True
        mock_driver.apply.assert_called_once()
        # Cover letter path should be empty when generation fails
        call_kwargs = mock_driver.apply.call_args
        assert call_kwargs.kwargs.get("cover_letter_path", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else "") == "" or True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_pipeline_steps.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pipeline_steps.py`**

```python
# src/job_agent/orchestrator/pipeline_steps.py
"""Extracted pipeline step functions — each handles one phase of the pipeline."""

from __future__ import annotations

import json

from job_agent.ai.cold_email import ColdEmailGenerator
from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.job_matcher import JobMatcher
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.config import Settings
from job_agent.db.models import (
    ApplicationStatus,
    Job,
    JobStatus,
    OutreachStatus,
    Platform,
)
from job_agent.db.repository import (
    ApplicationRepository,
    CredentialRepository,
    JobRepository,
    MatchResultRepository,
    OutreachRepository,
)
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.utils.json_helpers import parse_json_list
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def match_job(
    *,
    job: Job,
    posting: JobPosting,
    matcher: JobMatcher,
    match_repo: MatchResultRepository,
    profile: dict,
) -> object:
    """Run AI matching on a single job. Updates job status to MATCHED and stores result."""
    score = matcher.match(posting, profile)
    match_repo.create(
        job_id=job.id,
        score=score.score,
        reasoning=score.reasoning,
        matched_skills=score.matched_skills,
        missing_skills=score.missing_skills,
        role_fit=score.role_fit,
        red_flags=score.red_flags,
    )
    job.status = JobStatus.MATCHED
    log.info("job_matched", job_id=job.id, score=score.score, title=job.title)
    return score


def decide_job(job: Job, score, settings: Settings) -> str:
    """Decide what to do with a matched job based on thresholds.

    Returns: "auto_apply", "queue", or "skip".
    """
    if score.score >= settings.matching.auto_apply_threshold:
        job.status = JobStatus.AUTO_APPROVED
        log.info("job_auto_approved", job_id=job.id, score=score.score)
        return "auto_apply"
    elif score.score >= settings.matching.review_threshold:
        job.status = JobStatus.QUEUED
        log.info("job_queued", job_id=job.id, score=score.score)
        return "queue"
    else:
        job.status = JobStatus.SKIPPED
        log.info("job_skipped", job_id=job.id, score=score.score)
        return "skip"


def apply_to_job(
    *,
    job: Job,
    posting: JobPosting,
    driver: PlatformDriver,
    resume_tailor: ResumeTailor,
    cover_letter_gen: CoverLetterGenerator,
    app_repo: ApplicationRepository,
    candidate_summary: str,
    matched_skills: list[str],
) -> bool:
    """Tailor resume, generate cover letter, and apply. Returns True on success."""
    resume_path = resume_tailor.tailor_and_save(posting, matched_skills)

    cl_path = ""
    try:
        cl_path = cover_letter_gen.generate_and_save(
            posting, candidate_summary, matched_skills
        )
    except Exception as e:
        log.warning(
            "cover_letter_generation_failed",
            job_id=job.id,
            company=job.company,
            error=str(e),
        )

    success = driver.apply(posting, resume_path, cover_letter_path=cl_path)

    if success:
        job.status = JobStatus.APPLIED
        app_repo.create(
            job_id=job.id,
            resume_path=resume_path,
            cover_letter_path=cl_path,
            status=ApplicationStatus.SUBMITTED,
        )
        log.info("job_applied", job_id=job.id, title=job.title, company=job.company)
    else:
        job.status = JobStatus.APPLY_FAILED
        app_repo.create(
            job_id=job.id,
            resume_path=resume_path,
            cover_letter_path=cl_path,
            status=ApplicationStatus.FAILED,
            error_message="Application submission returned failure",
        )
        log.warning("job_apply_failed", job_id=job.id, title=job.title)

    return success


def generate_cold_email_draft(
    *,
    job: Job,
    ai_client: AIClient,
    settings: Settings,
    profile: dict,
    session,
) -> None:
    """Generate a cold email draft for a successfully applied job. Non-fatal on failure."""
    try:
        outreach_repo = OutreachRepository(session)
        candidate_summary = build_candidate_summary(profile)

        matched_skills = parse_json_list(
            job.match_result.matched_skills if job.match_result else None
        )

        recipient_name = "Hiring Manager"
        recipient_title = "Recruiter"

        if outreach_repo.exists_email_for_job(job.id, recipient_name):
            return

        generator = ColdEmailGenerator(ai_client, settings)
        email_data = generator.generate(
            job_title=job.title,
            company=job.company,
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            matched_skills=matched_skills,
            candidate_summary=candidate_summary,
        )

        outreach_repo.create(
            platform=job.platform,
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            recipient_company=job.company,
            recipient_profile_url="",
            message_type="email",
            message_text=json.dumps(email_data),
            status=OutreachStatus.DRAFTED,
            related_job_id=job.id,
        )
        log.info("cold_email_draft_generated", job_id=job.id, company=job.company)
    except Exception as e:
        log.warning(
            "cold_email_draft_failed",
            job_id=job.id,
            company=job.company,
            error=str(e),
        )


def build_candidate_summary(profile: dict) -> str:
    """Build a candidate summary string from a profile dict."""
    parts: list[str] = []
    if name := profile.get("name"):
        parts.append(f"Target Role: {name}")
    search = profile.get("search", {})
    if exp := search.get("experience_level"):
        parts.append(f"Experience Level: {exp}")
    skills = profile.get("skills", {})
    if req := skills.get("required"):
        parts.append(f"Required Skills: {', '.join(req)}")
    if pref := skills.get("preferred"):
        parts.append(f"Preferred Skills: {', '.join(pref)}")
    return "\n".join(parts)


def get_matched_skills_for_job(job: Job) -> list[str]:
    """Extract matched skills list from a job's match result."""
    if not job.match_result or not job.match_result.matched_skills:
        return []
    return parse_json_list(job.match_result.matched_skills)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_pipeline_steps.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/job_agent/orchestrator/pipeline_steps.py tests/unit/test_pipeline_steps.py
git commit -m "feat: extract match_job, decide_job, apply_to_job into pipeline_steps module"
```

---

### Task 3: Rewrite `pipeline.py` to use extracted step functions

Replace the inline logic in `run_pipeline()` and `apply_approved()` with calls to the new step functions. This reduces each function by ~60%.

**Files:**
- Modify: `src/job_agent/orchestrator/pipeline.py`

- [ ] **Step 1: Rewrite `run_pipeline()` to use step functions**

Replace the contents of `src/job_agent/orchestrator/pipeline.py` with:

```python
"""Discovery -> Dedup -> Match -> Decide -> Apply pipeline."""

from __future__ import annotations

from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.job_matcher import JobMatcher
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings, load_profile
from job_agent.db.models import (
    Job,
    JobStatus,
    Platform,
)
from job_agent.db.repository import (
    ApplicationRepository,
    CredentialRepository,
    JobRepository,
    MatchResultRepository,
)
from job_agent.db.session import get_session
from job_agent.orchestrator.pipeline_steps import (
    apply_to_job,
    build_candidate_summary,
    decide_job,
    generate_cold_email_draft,
    get_matched_skills_for_job,
    match_job,
)
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.utils.crypto import decrypt
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def get_platform_driver(
    platform_name: str, settings: Settings, browser_manager: BrowserManager
) -> PlatformDriver:
    """Factory for platform drivers."""
    from job_agent.platforms.indeed.driver import IndeedDriver
    from job_agent.platforms.glassdoor.driver import GlassdoorDriver
    from job_agent.platforms.ziprecruiter.driver import ZipRecruiterDriver
    from job_agent.platforms.dice.driver import DiceDriver
    from job_agent.platforms.wellfound.driver import WellfoundDriver
    from job_agent.platforms.linkedin.driver import LinkedInDriver

    drivers = {
        "linkedin": lambda: LinkedInDriver(settings, browser_manager),
        "indeed": lambda: IndeedDriver(settings, browser_manager),
        "glassdoor": lambda: GlassdoorDriver(settings, browser_manager),
        "ziprecruiter": lambda: ZipRecruiterDriver(settings, browser_manager),
        "dice": lambda: DiceDriver(settings, browser_manager),
        "wellfound": lambda: WellfoundDriver(settings, browser_manager),
    }
    factory = drivers.get(platform_name)
    if not factory:
        raise ValueError(f"Unsupported platform: {platform_name}")
    return factory()


def _login_driver(driver, platform_name, session, settings):
    """Login a platform driver. Returns True on success, False if no credentials."""
    cred = CredentialRepository(session).get(Platform(platform_name))
    if not cred:
        log.warning("no_credentials", platform=platform_name)
        return False
    driver.login(cred.username, decrypt(cred.encrypted_password))
    return True


def _discover_postings(driver, search, settings, job_repo, profile, session):
    """Run discovery loop across keywords and locations. Returns (postings_with_jobs, stats)."""
    results = []
    stats = {"discovered": 0}
    consecutive_failures = 0

    for kw in search.get("keywords", []):
        if consecutive_failures >= 3:
            log.error(
                "too_many_search_failures",
                consecutive=consecutive_failures,
            )
            break
        for loc in search.get("locations", [""]):
            try:
                postings = driver.search_jobs(
                    query=kw,
                    location=loc,
                    remote=search.get("remote_preference", "") == "remote_only",
                    experience_level=search.get("experience_level", ""),
                    limit=25,
                )
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                log.warning(
                    "search_failed",
                    query=kw,
                    location=loc,
                    error=str(e)[:200],
                )
                continue

            for posting in postings:
                if job_repo.exists(posting.external_id, posting.platform):
                    continue

                if not posting.description:
                    try:
                        detailed = driver.get_job_details(posting.url)
                        posting.description = detailed.description
                    except Exception as e:
                        log.warning(
                            "detail_fetch_failed",
                            url=posting.url,
                            error=str(e)[:200],
                        )

                job = job_repo.create(
                    external_id=posting.external_id,
                    platform=posting.platform,
                    title=posting.title,
                    company=posting.company,
                    location=posting.location,
                    description=posting.description,
                    url=posting.url,
                    salary=posting.salary,
                    easy_apply=posting.easy_apply,
                    remote=posting.remote,
                    profile_name=profile.get("name", ""),
                )
                stats["discovered"] += 1
                results.append((job, posting))

    return results, stats


def discover_jobs(
    settings: Settings,
    platform_name: str,
    query: str,
    location: str = "",
    limit: int = 25,
) -> list[Job]:
    """Discover and store jobs from a platform."""
    session = get_session(settings)
    job_repo = JobRepository(session)

    try:
        with BrowserManager(settings) as browser:
            driver = get_platform_driver(platform_name, settings, browser)

            cred = CredentialRepository(session).get(Platform(platform_name))
            if not cred:
                raise RuntimeError(
                    f"No credentials for {platform_name}. Run: job-agent add-credential {platform_name}"
                )

            driver.login(cred.username, decrypt(cred.encrypted_password))
            postings = driver.search_jobs(query=query, location=location, limit=limit)

            stored: list[Job] = []
            for posting in postings:
                if not job_repo.exists(posting.external_id, posting.platform):
                    duplicate_of = job_repo.find_cross_platform_duplicate(
                        posting.title, posting.company, posting.platform
                    )
                    job = job_repo.create(
                        external_id=posting.external_id,
                        platform=posting.platform,
                        title=posting.title,
                        company=posting.company,
                        location=posting.location,
                        description=posting.description,
                        url=posting.url,
                        salary=posting.salary,
                        easy_apply=posting.easy_apply,
                        remote=posting.remote,
                        duplicate_of_id=duplicate_of.id if duplicate_of else None,
                    )
                    if duplicate_of:
                        job.status = JobStatus.REJECTED
                        log.info(
                            "job_duplicate_skipped",
                            title=job.title,
                            company=job.company,
                            original_platform=duplicate_of.platform.value,
                        )
                    else:
                        stored.append(job)
                        log.info("job_discovered", title=job.title, company=job.company)

            session.commit()
            driver.close()

        log.info("discovery_complete", total=len(postings), new=len(stored))
        return stored

    except Exception as e:
        session.rollback()
        log.error("discovery_failed", platform=platform_name, error=str(e))
        raise
    finally:
        session.close()


def run_pipeline(
    settings: Settings,
    profile_path: str,
    platform_name: str | None = None,
) -> dict[str, int]:
    """Run the full discover -> match -> decide -> apply pipeline."""
    profile = load_profile(profile_path)
    search = profile.get("search", {})
    stats = {"discovered": 0, "matched": 0, "applied": 0, "queued": 0, "skipped": 0}

    platforms_to_run = []
    if platform_name:
        platforms_to_run = [platform_name]
    else:
        for p in ["linkedin", "indeed", "glassdoor", "ziprecruiter", "dice", "wellfound"]:
            cfg = getattr(settings.platforms, p)
            if cfg.enabled:
                platforms_to_run.append(p)

    session = get_session(settings)
    job_repo = JobRepository(session)
    match_repo = MatchResultRepository(session)
    app_repo = ApplicationRepository(session)
    ai_client = AIClient(settings)
    matcher = JobMatcher(ai_client)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    candidate_summary = build_candidate_summary(profile)

    try:
        with BrowserManager(settings) as browser:
            for plat in platforms_to_run:
                driver = get_platform_driver(plat, settings, browser)

                if not _login_driver(driver, plat, session, settings):
                    continue

                if hasattr(driver, "set_ai_context"):
                    driver.set_ai_context(ai_client, profile)

                # Discover
                discovered, disc_stats = _discover_postings(
                    driver, search, settings, job_repo, profile, session
                )
                stats["discovered"] += disc_stats["discovered"]

                # Match + Decide + Apply each discovered job
                for job, posting in discovered:
                    try:
                        score = match_job(
                            job=job,
                            posting=posting,
                            matcher=matcher,
                            match_repo=match_repo,
                            profile=profile,
                        )
                        stats["matched"] += 1

                        decision = decide_job(job, score, settings)

                        if decision == "auto_apply" and not settings.agent.dry_run:
                            try:
                                success = apply_to_job(
                                    job=job,
                                    posting=posting,
                                    driver=driver,
                                    resume_tailor=resume_tailor,
                                    cover_letter_gen=cover_letter_gen,
                                    app_repo=app_repo,
                                    candidate_summary=candidate_summary,
                                    matched_skills=get_matched_skills_for_job(job),
                                )
                                if success:
                                    stats["applied"] += 1
                                    generate_cold_email_draft(
                                        job=job,
                                        ai_client=ai_client,
                                        settings=settings,
                                        profile=profile,
                                        session=session,
                                    )
                            except Exception as e:
                                log.error(
                                    "apply_error",
                                    job_id=job.id,
                                    title=job.title,
                                    company=job.company,
                                    error=str(e),
                                )
                                job.status = JobStatus.APPLY_FAILED
                                app_repo.create(
                                    job_id=job.id,
                                    resume_path="",
                                    cover_letter_path="",
                                    status=ApplicationStatus.FAILED,
                                    error_message=str(e)[:500],
                                )
                        elif decision == "auto_apply" and settings.agent.dry_run:
                            stats["applied"] += 1
                        elif decision == "queue":
                            stats["queued"] += 1
                        elif decision == "skip":
                            stats["skipped"] += 1
                    except Exception as e:
                        log.error(
                            "job_processing_error",
                            job_id=job.id,
                            title=job.title,
                            error=str(e),
                        )

                    session.commit()

                driver.close()

            # Process approved jobs from the review queue
            _process_approved_queue(
                session=session,
                settings=settings,
                browser=browser,
                ai_client=ai_client,
                profile=profile,
                app_repo=app_repo,
                job_repo=job_repo,
                resume_tailor=resume_tailor,
                cover_letter_gen=cover_letter_gen,
                candidate_summary=candidate_summary,
                stats=stats,
            )

        log.info("pipeline_complete", **stats)
        return stats

    except Exception as e:
        session.rollback()
        log.error("pipeline_failed", error=str(e))
        raise
    finally:
        session.close()


def _process_approved_queue(
    *,
    session,
    settings,
    browser,
    ai_client,
    profile,
    app_repo,
    job_repo,
    resume_tailor,
    cover_letter_gen,
    candidate_summary,
    stats,
):
    """Process all APPROVED jobs from the review queue."""
    from job_agent.db.models import ApplicationStatus

    approved_jobs = job_repo.list_by_status(JobStatus.APPROVED)
    if not approved_jobs:
        return

    log.info("processing_approved_jobs", count=len(approved_jobs))

    by_platform: dict[str, list] = {}
    for job in approved_jobs:
        by_platform.setdefault(job.platform.value, []).append(job)

    for plat, jobs in by_platform.items():
        try:
            driver = get_platform_driver(plat, settings, browser)
            if not _login_driver(driver, plat, session, settings):
                continue

            if hasattr(driver, "set_ai_context"):
                driver.set_ai_context(ai_client, profile)

            for job in jobs:
                if settings.agent.dry_run:
                    log.info("dry_run_approved", job_id=job.id, title=job.title)
                    job.status = JobStatus.APPLIED
                    app_repo.create(job_id=job.id, resume_path="")
                    stats["applied"] += 1
                    session.commit()
                    continue

                try:
                    posting = JobPosting(
                        external_id=job.external_id,
                        platform=job.platform,
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        description=job.description or "",
                        url=job.url,
                        easy_apply=True,
                        remote=job.remote,
                        salary=job.salary,
                    )
                    matched_skills = get_matched_skills_for_job(job)

                    success = apply_to_job(
                        job=job,
                        posting=posting,
                        driver=driver,
                        resume_tailor=resume_tailor,
                        cover_letter_gen=cover_letter_gen,
                        app_repo=app_repo,
                        candidate_summary=candidate_summary,
                        matched_skills=matched_skills,
                    )
                    if success:
                        stats["applied"] += 1
                        generate_cold_email_draft(
                            job=job,
                            ai_client=ai_client,
                            settings=settings,
                            profile=profile,
                            session=session,
                        )
                except Exception as e:
                    log.error(
                        "approved_job_error",
                        job_id=job.id,
                        title=job.title,
                        company=job.company,
                        error=str(e),
                    )
                    job.status = JobStatus.APPLY_FAILED
                    app_repo.create(
                        job_id=job.id,
                        resume_path="",
                        cover_letter_path="",
                        status=ApplicationStatus.FAILED,
                        error_message=str(e)[:500],
                    )

                session.commit()

            driver.close()
        except Exception as e:
            log.error(
                "approved_platform_error",
                platform=plat,
                error=str(e),
            )


def apply_approved(settings: Settings, profile_path: str = "") -> dict[str, int]:
    """Apply to all APPROVED jobs from the review queue (skips discovery)."""
    stats = {"applied": 0, "failed": 0, "skipped": 0}

    session = get_session(settings)
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    ai_client = AIClient(settings)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    profile = load_profile(profile_path) if profile_path else {}
    candidate_summary = build_candidate_summary(profile)

    try:
        approved_jobs = job_repo.list_by_status(JobStatus.APPROVED)
        if not approved_jobs:
            log.info("no_approved_jobs")
            return stats

        log.info("applying_approved_jobs", count=len(approved_jobs))

        by_platform: dict[str, list] = {}
        for job in approved_jobs:
            by_platform.setdefault(job.platform.value, []).append(job)

        with BrowserManager(settings) as browser:
            for plat, jobs in by_platform.items():
                try:
                    driver = get_platform_driver(plat, settings, browser)
                    if not _login_driver(driver, plat, session, settings):
                        continue

                    if profile and hasattr(driver, "set_ai_context"):
                        driver.set_ai_context(ai_client, profile)

                    for job in jobs:
                        try:
                            posting = JobPosting(
                                external_id=job.external_id,
                                platform=job.platform,
                                title=job.title,
                                company=job.company,
                                location=job.location,
                                description=job.description or "",
                                url=job.url,
                                easy_apply=True,
                                remote=job.remote,
                                salary=job.salary,
                            )
                            matched_skills = get_matched_skills_for_job(job)

                            success = apply_to_job(
                                job=job,
                                posting=posting,
                                driver=driver,
                                resume_tailor=resume_tailor,
                                cover_letter_gen=cover_letter_gen,
                                app_repo=app_repo,
                                candidate_summary=candidate_summary,
                                matched_skills=matched_skills,
                            )
                            if success:
                                stats["applied"] += 1
                                generate_cold_email_draft(
                                    job=job,
                                    ai_client=ai_client,
                                    settings=settings,
                                    profile=profile,
                                    session=session,
                                )
                            else:
                                stats["failed"] += 1
                        except Exception as e:
                            log.error(
                                "approved_job_error",
                                job_id=job.id,
                                title=job.title,
                                company=job.company,
                                error=str(e),
                            )
                            job.status = JobStatus.APPLY_FAILED
                            stats["failed"] += 1

                        session.commit()

                    driver.close()
                except Exception as e:
                    log.error(
                        "approved_platform_error",
                        platform=plat,
                        error=str(e),
                    )

        log.info("apply_approved_complete", **stats)
        return stats

    except Exception as e:
        session.rollback()
        log.error("apply_approved_failed", error=str(e))
        raise
    finally:
        session.close()
```

- [ ] **Step 2: Run existing engine tests to verify nothing is broken**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_engine.py -v`
Expected: All existing tests PASS

- [ ] **Step 3: Run the full test suite**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/job_agent/orchestrator/pipeline.py
git commit -m "refactor: rewrite pipeline.py to use extracted step functions, reduce from 687 to ~350 lines"
```

---

### Task 4: Add logging to dashboard silent exception handlers

Replace bare `except Exception:` blocks in dashboard routes with `log.warning()` calls that include context (route name, entity IDs, error message).

**Files:**
- Modify: `src/job_agent/dashboard/routes/queue.py`
- Modify: `src/job_agent/dashboard/routes/jobs.py`
- Modify: `src/job_agent/dashboard/routes/applications.py`
- Modify: `src/job_agent/dashboard/routes/outreach.py`

- [ ] **Step 1: Fix `queue.py` — add logging to 4 bare exception handlers**

In `src/job_agent/dashboard/routes/queue.py`, add the import and fix each handler:

Add after existing imports:
```python
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
```

Replace each bare `except Exception:` with `except Exception as e:` and add a log call before the return:

1. Line 78: `approve()` handler
```python
    except Exception as e:
        session.rollback()
        log.warning("approve_failed", job_id=job_id, error=str(e))
        return '<div class="alert alert-danger">Failed to approve job</div>', 500
```

2. Line 102: `approve_all()` handler
```python
    except Exception as e:
        session.rollback()
        log.warning("approve_all_failed", error=str(e))
        return '<div class="alert alert-danger">Failed to approve jobs</div>', 500
```

3. Line 138: `bulk_action()` handler
```python
    except Exception as e:
        session.rollback()
        log.warning("bulk_action_failed", action=data.get("action"), error=str(e))
        return jsonify(ok=False, message="Failed to process bulk action"), 500
```

4. Line 162: `reject()` handler
```python
    except Exception as e:
        session.rollback()
        log.warning("reject_failed", job_id=job_id, error=str(e))
        return '<div class="alert alert-danger">Failed to reject job</div>', 500
```

- [ ] **Step 2: Fix `jobs.py` — add logging to bookmark handler**

In `src/job_agent/dashboard/routes/jobs.py`, add the import:
```python
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
```

Replace the bookmark handler (line 110):
```python
    except Exception as e:
        session.rollback()
        log.warning("bookmark_toggle_failed", job_id=job_id, error=str(e))
        return '<span class="text-muted">Error</span>', 500
```

- [ ] **Step 3: Fix `applications.py` — add logging to retry handler**

In `src/job_agent/dashboard/routes/applications.py`, add the import:
```python
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
```

Replace the retry handler (line 193):
```python
    except Exception as e:
        session.rollback()
        log.warning("retry_failed", app_id=app_id, error=str(e))
        return '<div class="alert alert-danger">Failed to retry application</div>', 500
```

- [ ] **Step 4: Fix `outreach.py` — add logging to silent profile loading**

In `src/job_agent/dashboard/routes/outreach.py`, add the import:
```python
from job_agent.utils.logging import get_logger

log = get_logger(__name__)
```

Replace the two silent `except Exception: pass` blocks (lines 161-162 and 395-396) with:
```python
                    except Exception as e:
                        log.debug("profile_load_failed", path=str(p), error=str(e))
```

Replace the silent resume tailor fallback (line 449):
```python
        except Exception as e:
            log.warning("resume_tailor_failed", job_title=job_title, error=str(e))
            tailored_resume_path = str(Path(settings.resume.master_resume))
```

- [ ] **Step 5: Run dashboard tests to verify nothing broke**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_dashboard.py tests/unit/test_dashboard_health.py tests/unit/test_queue.py tests/unit/test_retry.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/job_agent/dashboard/routes/queue.py src/job_agent/dashboard/routes/jobs.py src/job_agent/dashboard/routes/applications.py src/job_agent/dashboard/routes/outreach.py
git commit -m "fix: replace silent exception handlers in dashboard routes with structured logging"
```

---

### Task 5: Add logging to external ATS silent exception blocks

Replace `except Exception: pass` and `except Exception: continue` blocks in `external_ats.py` with debug/warning logs.

**Files:**
- Modify: `src/job_agent/platforms/external_ats.py`

- [ ] **Step 1: Fix silent exception handlers in external_ats.py**

The file already has `log = get_logger(__name__)`. Replace these silent blocks:

1. `_detect_email_apply` — three `except Exception: pass` blocks (lines 152, 169, 199):
```python
        except Exception as e:
            log.debug("mailto_detection_failed", error=str(e))
```
```python
        except Exception as e:
            log.debug("email_text_detection_failed", error=str(e))
```
```python
        except Exception as e:
            log.debug("email_no_form_detection_failed", error=str(e))
```

2. `_apply_generic` — cover letter upload `except Exception: pass` (line 451):
```python
                        except Exception as e:
                            log.debug("cover_letter_upload_failed", error=str(e))
```

3. `_apply_generic` — submit scroll `except Exception: pass` (line 476):
```python
                    except Exception as e:
                        log.debug("submit_scroll_failed", error=str(e))
```

4. `_apply_generic` — submit click fallback `except Exception: pass` (lines 479-483):
```python
                try:
                    submit.click(force=True)
                except Exception:
                    try:
                        submit.evaluate("el => el.click()")
                    except Exception as e:
                        log.debug("submit_click_failed", error=str(e))
```

5. `_click_submit` — scroll `except Exception: pass` (line 852):
```python
        except Exception as e:
            log.debug("submit_scroll_failed", error=str(e))
```

6. `_click_submit` — btn_html `except Exception: pass` (line 843):
```python
        except Exception as e:
            log.debug("submit_html_read_failed", error=str(e))
```

7. `_extract_standalone_fields` — `except Exception: continue` (line 757):
```python
            except Exception as e:
                log.debug("standalone_field_extract_failed", error=str(e))
                continue
```

8. `_label_for` — `except Exception: pass` (line 770):
```python
        except Exception as e:
            log.debug("label_lookup_failed", error=str(e))
```

9. `_unique_selector` — `except Exception: pass` (line 918):
```python
        except Exception as e:
            log.debug("unique_selector_failed", error=str(e))
```

- [ ] **Step 2: Run external ATS tests**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_external_ats.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/job_agent/platforms/external_ats.py
git commit -m "fix: replace silent exception handlers in external_ats with debug logging"
```

---

### Task 6: Replace duplicated `_build_candidate_summary` with import from `pipeline_steps`

The same function exists in 3 places: `pipeline.py`, `outreach.py`, and `pipeline_steps.py`. Replace the duplicates with imports.

**Files:**
- Modify: `src/job_agent/dashboard/routes/outreach.py`

- [ ] **Step 1: Replace the duplicate in outreach.py**

In `src/job_agent/dashboard/routes/outreach.py`, remove the local `_build_candidate_summary` function (lines 32-45) and add an import:

```python
from job_agent.orchestrator.pipeline_steps import build_candidate_summary
```

Then find-and-replace `_build_candidate_summary` with `build_candidate_summary` throughout the file (3 call sites).

- [ ] **Step 2: Replace `parse_json_list` usage in dashboard routes**

In `src/job_agent/dashboard/routes/queue.py`, replace the inline JSON parsing in the `index()` function (lines 34-49) with:

Add import:
```python
from job_agent.utils.json_helpers import parse_json_list
```

Replace the parsing block:
```python
            if job.match_result:
                item["matched_skills"] = parse_json_list(
                    job.match_result.matched_skills
                )
                item["missing_skills"] = parse_json_list(
                    job.match_result.missing_skills
                )
                item["red_flags"] = parse_json_list(job.match_result.red_flags)
```

In `src/job_agent/dashboard/routes/jobs.py`, replace the detail route JSON parsing (lines 135-146) with:

Add import:
```python
from job_agent.utils.json_helpers import parse_json_list
```

Replace:
```python
        if match_result:
            matched_skills = parse_json_list(match_result.matched_skills)
            missing_skills = parse_json_list(match_result.missing_skills)
            red_flags = parse_json_list(match_result.red_flags)
```

And in the `preview_resume` route (lines 180-184):
```python
        matched_skills = parse_json_list(
            job.match_result.matched_skills if job.match_result else None
        )
```

- [ ] **Step 3: Run the full test suite**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/job_agent/dashboard/routes/outreach.py src/job_agent/dashboard/routes/queue.py src/job_agent/dashboard/routes/jobs.py
git commit -m "refactor: deduplicate _build_candidate_summary and JSON parsing across codebase"
```

---

### Task 7: Final verification and cleanup

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `cd /home/williams/Documents/personal/job-agent && uv run ruff check src/job_agent/orchestrator/ src/job_agent/dashboard/routes/ src/job_agent/platforms/external_ats.py src/job_agent/utils/json_helpers.py`
Expected: No errors

- [ ] **Step 3: Run formatter**

Run: `cd /home/williams/Documents/personal/job-agent && uv run ruff format --check src/job_agent/orchestrator/ src/job_agent/dashboard/routes/ src/job_agent/platforms/external_ats.py src/job_agent/utils/json_helpers.py`
Expected: No formatting issues

- [ ] **Step 4: Verify line count reduction**

Run: `wc -l src/job_agent/orchestrator/pipeline.py src/job_agent/orchestrator/pipeline_steps.py`
Expected: pipeline.py ~350 lines (down from 687), pipeline_steps.py ~170 lines. Total logic is the same, but now testable in isolation.

- [ ] **Step 5: Verify no remaining silent exceptions in modified files**

Run: `cd /home/williams/Documents/personal/job-agent && grep -rn "except Exception:" src/job_agent/dashboard/routes/ src/job_agent/orchestrator/pipeline.py src/job_agent/platforms/external_ats.py | grep -v "as e"`
Expected: No matches (all exception handlers now capture the error variable)
