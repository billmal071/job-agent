# Job Agent

Autonomous job application agent that automates the entire job search lifecycle: discovering jobs on LinkedIn/Indeed/Glassdoor, scoring them against configurable profiles using Claude API, tailoring CVs for ATS optimization, auto-applying to high-confidence matches, queuing medium matches for review, and conducting LinkedIn recruiter outreach.

## Features

- **Multi-Platform Support** — LinkedIn, Indeed, Glassdoor
- **AI-Powered Matching** — Claude API scores jobs 0.0–1.0 against your profile
- **Resume Tailoring** — Auto-generates ATS-optimized resumes per job (PDF)
- **Cover Letters** — AI-generated, customizable tone
- **Tiered Autonomy** — Auto-apply (≥0.90), queue for review (0.70–0.89), skip (<0.70)
- **Web Dashboard** — Flask + HTMX + Bootstrap 5 with overview, jobs, review queue, applications, outreach, analytics, settings
- **LinkedIn Outreach** — Personalized connection requests and InMail to recruiters
- **Anti-Detection** — Stealth browser config, human-like typing/mouse, session rotation
- **Scheduling** — APScheduler with configurable activity windows
- **Notifications** — Email (SMTP) and webhooks (Slack/Discord)
- **Security** — Fernet-encrypted credentials, SQLite outside repo

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

```bash
# Clone and install
git clone https://github.com/billmal071/job-agent.git
cd job-agent
uv sync

# Install Playwright browsers
uv run playwright install chromium

# Copy and configure environment
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# Run the setup wizard
uv run job-agent setup
```

### Usage

```bash
# Initialize the database
uv run job-agent init-db

# Add platform credentials (encrypted)
uv run job-agent add-credential linkedin

# Create your profile
cp config/profiles/example.yaml config/profiles/myprofile.yaml
# Edit myprofile.yaml with your preferences

# Add your master resume
# Place your resume at config/resumes/master.md

# Search for jobs (no applying)
uv run job-agent search --platform linkedin --query "Python Developer"

# Run the full pipeline once
uv run job-agent run --profile config/profiles/myprofile.yaml --once

# Run with dry-run (discover + match only)
uv run job-agent run --profile config/profiles/myprofile.yaml --once --dry-run

# Run on a schedule
uv run job-agent run --profile config/profiles/myprofile.yaml

# Start the web dashboard
uv run job-agent dashboard
```

### Docker

```bash
cp .env.example .env
# Edit .env with your keys

# Start the dashboard
docker compose up dashboard

# Run the agent once
docker compose run --rm agent
```

## Configuration

### Profile System

Each profile (YAML) defines your job search criteria:

```yaml
name: "Senior Python Developer"
search:
  keywords: ["Senior Python Developer", "Backend Engineer"]
  locations: ["Remote", "San Francisco, CA"]
  experience_level: "senior"
  remote_preference: "remote_first"
  salary_minimum: 150000
skills:
  required: ["Python", "SQL", "REST APIs"]
  preferred: ["FastAPI", "Django", "AWS", "Docker"]
exclusions:
  companies: ["SpamCorp"]
  keywords: ["unpaid", "intern"]
```

### Rate Limits

Configurable per platform in `config/default.yaml`:

| Platform   | Requests/min | Apps/day | Session  | Cooldown |
|------------|-------------|----------|----------|----------|
| LinkedIn   | 3           | 25       | 45 min   | 30 min   |
| Indeed     | 5           | 40       | 60 min   | 20 min   |
| Glassdoor  | 4           | 30       | 60 min   | 20 min   |

### Autonomy Thresholds

| Score       | Action                    |
|-------------|---------------------------|
| ≥ 0.90      | Auto-apply                |
| 0.70 – 0.89 | Queue for manual review   |
| < 0.70      | Skip                      |

All thresholds are configurable in `config/default.yaml` or via the dashboard.

## Project Structure

```
job-agent/
├── config/              # Default config + profile templates
├── migrations/          # Alembic database migrations
├── src/job_agent/
│   ├── ai/              # Claude API: matching, resume tailoring, cover letters
│   ├── browser/         # Playwright: manager, stealth, humanizer, auth
│   ├── dashboard/       # Flask web UI: routes, templates, static
│   ├── db/              # SQLAlchemy models, session, repositories
│   ├── notifications/   # Email + webhook notifiers
│   ├── orchestrator/    # Pipeline engine, scheduler, review queue
│   ├── platforms/       # LinkedIn, Indeed, Glassdoor drivers
│   └── utils/           # Crypto, logging, rate limiter
└── tests/               # Unit and integration tests
```

## Security

- Credentials are Fernet-encrypted, key stored at `~/.job-agent/fernet.key` (0600 perms)
- API keys live in `.env` (gitignored)
- Database at `~/.job-agent/agent.db` (outside repo)
- Browser state at `~/.job-agent/browser_state/`

## Testing

```bash
uv run pytest tests/ -v
```

## License

MIT
