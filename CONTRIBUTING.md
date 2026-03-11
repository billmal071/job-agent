# Contributing to Job Agent

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/billmal071/job-agent.git
cd job-agent
uv sync
uv run playwright install chromium
uv run job-agent init-db
```

## Running the Dashboard

```bash
uv run job-agent dashboard
# Visit http://127.0.0.1:5000
```

## Running Tests

```bash
uv run pytest tests/ -v
```

## Project Structure

- `src/job_agent/ai/` — AI client, matching, resume tailoring, screening answers
- `src/job_agent/browser/` — Playwright/Camoufox browser management
- `src/job_agent/dashboard/` — Flask web UI
- `src/job_agent/db/` — SQLAlchemy models and repositories
- `src/job_agent/platforms/` — Platform-specific discovery and application drivers
- `src/job_agent/orchestrator/` — Pipeline engine and scheduler

## Adding a New Platform

1. Create a new directory under `src/job_agent/platforms/<platform>/`
2. Implement `discovery.py` with a class that discovers jobs
3. Implement `applicator.py` with a class that applies to jobs
4. Add the platform to `src/job_agent/db/models.py` Platform enum
5. Register the platform in the orchestrator pipeline

## Adding a New ATS

1. Add detection pattern in `src/job_agent/platforms/external_ats.py`
2. Implement `_apply_<ats_name>()` method in `ExternalATSApplicator`
3. Add the ATS to the `detect_ats()` function

## Guidelines

- Use `uv` for package management (not pip)
- Follow existing code patterns and conventions
- Add tests for new functionality
- Don't commit personal profiles, resumes, or API keys
- Keep PRs focused — one feature or fix per PR

## Reporting Issues

- Check existing issues first
- Include steps to reproduce
- Include relevant error logs (redact personal info)
