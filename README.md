# Job Agent

Autonomous job application agent that automates the entire job search lifecycle: discovering jobs on LinkedIn/Indeed/Glassdoor, scoring them against configurable profiles using AI, tailoring CVs for ATS optimization, auto-applying to high-confidence matches, queuing medium matches for review, and conducting LinkedIn recruiter outreach.

## Demo

https://github.com/billmal071/job-agent/releases/download/v0.1.0/demo.mp4

## Features

- **Multi-Platform Discovery** — LinkedIn, Indeed, Glassdoor, ZipRecruiter, Dice, Wellfound
- **External ATS Support** — Automatically handles Greenhouse, Lever, Workday, Ashby, and generic application forms when job boards redirect to company sites
- **AI-Powered Matching** — Scores jobs 0.0–1.0 against your profile using configurable AI providers
- **Multi-AI Provider** — Google Gemini (free), Groq (free), OpenRouter, Ollama (local), Anthropic Claude
- **Resume Tailoring** — Auto-generates ATS-optimized resumes per job (PDF)
- **Cover Letters** — AI-generated, customizable tone (professional, casual, formal)
- **Screening Question Answering** — AI fills out application screening questions (multiple choice, free text, dropdowns)
- **CV-to-Profile Generator** — Upload your resume and AI creates your search profile automatically
- **Tiered Autonomy** — Auto-apply (≥0.80), queue for review (0.70–0.79), skip (<0.70) — all thresholds configurable
- **Web Dashboard** — Flask + HTMX + Bootstrap 5 with overview, jobs, review queue, applications, outreach, analytics, settings
- **Cold Email Outreach** — AI-generated personalized cold emails and LinkedIn connection requests to recruiters
- **Easy Apply Detection** — Identifies and prioritizes one-click apply jobs on LinkedIn, Indeed, and Glassdoor
- **Anti-Detection** — Camoufox stealth browser, human-like typing/mouse, random delays, session rotation
- **Email-to-Apply** — Detects "email your resume" pages and sends applications via SMTP with resume/cover letter attached
- **Scheduling** — APScheduler with configurable activity windows (default 8am–11pm)
- **Notifications** — Email (SMTP) and webhooks (Slack/Discord)
- **Security** — Fernet-encrypted credentials, SQLite outside repo, browser state persistence

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

# Initialize the database
uv run job-agent init-db

# Start the dashboard
uv run job-agent dashboard
# Visit http://127.0.0.1:5000/settings to configure everything from the UI
```

> **Tip:** You can configure your AI provider, platform credentials, matching thresholds, and notifications entirely from the dashboard — no need to edit config files.

Alternatively, configure via `.env`:
```bash
cp .env.example .env
# Edit .env — set your AI provider and API key
# Free options: Gemini (default), Groq, Ollama (local)
```

### Create Your Profile

**Option A: Generate from your CV (recommended)**

1. Go to `http://127.0.0.1:5000/settings`
2. Upload your resume (PDF or DOCX) in the "Generate Profile from CV" section
3. AI extracts your skills, experience level, and target roles automatically
4. Your resume is also saved as the master template for tailoring

**Option B: Create manually**

```bash
cp config/profiles/example.yaml config/profiles/myprofile.yaml
# Edit myprofile.yaml with your preferences
# Place your resume at config/resumes/master.pdf
```

### Run the Pipeline

```bash
# Run the full pipeline once
uv run job-agent run --profile config/profiles/myprofile.yaml --once

# Dry-run (discover + match only, no applications)
uv run job-agent run --profile config/profiles/myprofile.yaml --once --dry-run

# Run on a schedule (checks every hour, respects activity window)
uv run job-agent run --profile config/profiles/myprofile.yaml

# Apply to approved review queue jobs
uv run job-agent apply-approved

# Search without applying
uv run job-agent search --platform linkedin --query "Python Developer" --location "Remote"

# Run on a specific platform only
uv run job-agent run --profile config/profiles/myprofile.yaml --once --platform linkedin
```

### First-Time Login

On the first run for each platform, you'll need to log in manually in the browser window:

1. Set `headless: false` in `config/default.yaml` under `browser:`
2. Run the pipeline — a browser window will open
3. Complete the login (including any 2FA/CAPTCHA challenges)
4. The agent waits up to 120 seconds for you to finish
5. Your session is saved to `~/.job-agent/browser_state/` and reused on future runs

**Indeed & Glassdoor** use Google OAuth — when the "Sign in with Google" button appears, click it and complete the Google login flow in the popup. The agent detects this automatically.

Once sessions are saved, you can switch back to `headless: true` for unattended runs.

## How the Pipeline Works

```
Discover → Match → Decide → Tailor → Apply → Track
```

1. **Discover** — Searches jobs across all connected platforms using your profile keywords and locations
2. **Deduplicate** — Skips jobs already seen (external ID matching)
3. **Match** — AI scores each job 0.0–1.0 against your profile (skills, experience, salary, location)
4. **Decide** — Based on score:
   - **≥ 0.80** → Auto-apply
   - **0.70 – 0.79** → Queue for manual review in dashboard
   - **< 0.70** → Skip
5. **Tailor** — For each application: generates an ATS-optimized resume and cover letter
6. **Apply** — Submits the application:
   - **Easy Apply** jobs → fills the platform's quick-apply form
   - **External ATS** (Greenhouse, Lever, Workday, Ashby) → navigates to the ATS, detects form fields, uploads resume, fills screening questions via AI, and submits
   - **Email apply** pages → sends resume + cover letter via SMTP
   - **Generic forms** → AI-powered field detection and filling
7. **Track** — Stores results in the database with status, match reasoning, and error details

## Dashboard

The web dashboard at `http://127.0.0.1:5000` provides:

| Page | Description |
|------|-------------|
| **Overview** | Summary stats, recent activity timeline, agent run history |
| **Jobs** | All discovered jobs with match scores, details, and filtering by status |
| **Review Queue** | Medium-scoring jobs awaiting approval. Approve or reject — approved jobs are applied to on the next run |
| **Applications** | All submitted applications with status tracking (pending, submitted, confirmed, failed). Export to CSV |
| **Outreach** | AI-generated cold emails and LinkedIn connection request drafts. Track engagement status |
| **Analytics** | Score distribution histogram, activity timeline, platform breakdown charts |
| **Settings** | AI provider, platform credentials, matching thresholds, email/Slack notifications, CV-to-profile generator |

### Dashboard Actions

From the dashboard you can:

- **Run the pipeline** on demand (discover, match, apply)
- **Approve/reject** jobs in the review queue
- **Configure AI provider** and API keys (no restart needed)
- **Add platform credentials** (encrypted with Fernet)
- **Adjust thresholds** for auto-apply and review queue
- **Upload your CV** to auto-generate a search profile
- **Set up notifications** — email alerts and Slack/Discord webhooks
- **Export** application data to CSV

## Multiple Profiles

Create multiple profiles for different job searches:

```bash
config/profiles/fullstack.yaml    → config/resumes/master.pdf
config/profiles/devops.yaml       → config/resumes/master-devops.pdf

# Run each independently
uv run job-agent run --profile config/profiles/fullstack.yaml --once
uv run job-agent run --profile config/profiles/devops.yaml --once
```

Each profile specifies its own keywords, locations, skills, salary expectations, and resume template.

## Docker

```bash
cp .env.example .env
# Edit .env with your keys

# Start the dashboard
docker compose up dashboard

# Run the agent once
docker compose run --rm agent
```

## AI Providers

Job Agent supports multiple AI providers. Choose the one that works best for you:

| Provider | Cost | Setup |
|----------|------|-------|
| **Google Gemini** (default) | Free (15 RPM) | Get key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Groq** | Free tier | Get key at [console.groq.com](https://console.groq.com) |
| **Ollama** | Free (local) | Install from [ollama.com](https://ollama.com), then `ollama pull llama3.1` |
| **OpenRouter** | Some free models | Get key at [openrouter.ai/keys](https://openrouter.ai/keys) |
| **Anthropic Claude** | Paid | Get key at [console.anthropic.com](https://console.anthropic.com) |

Set via the **dashboard Settings page** at `http://127.0.0.1:5000/settings`, or in `.env`:
```bash
JOB_AGENT_AI_PROVIDER=gemini          # or groq, ollama, openrouter, anthropic
JOB_AGENT_GEMINI_API_KEY=your-key     # set the key for your chosen provider
```

## Configuration

### Profile Schema

```yaml
name: "Senior Python Developer"

search:
  keywords: ["Senior Python Developer", "Backend Engineer"]
  locations: ["Remote", "San Francisco, CA"]
  experience_level: "senior"        # entry, mid, senior, lead
  remote_preference: "remote_first" # onsite, hybrid, remote_only, remote_first
  salary_minimum: 150000

skills:
  required: ["Python", "SQL", "REST APIs"]
  preferred: ["FastAPI", "Django", "AWS", "Docker"]

exclusions:
  companies: ["SpamCorp"]
  keywords: ["unpaid", "intern"]

resume_template: "master"
cover_letter_tone: "professional"   # professional, casual, formal
```

Or just upload your CV from the dashboard and let AI generate this for you.

### Rate Limits

Configurable per platform in `config/default.yaml`:

| Platform      | Requests/min | Apps/day | Session  | Cooldown |
|---------------|-------------|----------|----------|----------|
| LinkedIn      | 3           | 25       | 45 min   | 30 min   |
| Indeed        | 5           | 40       | 60 min   | 20 min   |
| Glassdoor     | 4           | 30       | 60 min   | 20 min   |
| ZipRecruiter  | 5           | 40       | 60 min   | 20 min   |
| Dice          | 4           | 35       | 60 min   | 20 min   |
| Wellfound     | 3           | 20       | 45 min   | 25 min   |

### Autonomy Thresholds

| Score       | Action                    |
|-------------|---------------------------|
| ≥ 0.80      | Auto-apply                |
| 0.70 – 0.79 | Queue for manual review   |
| < 0.70      | Skip                      |

Thresholds are configurable from `config/default.yaml` or the dashboard Settings page. Dashboard changes persist to `.env` and survive restarts.

## External ATS Support

When a job board redirects to a company's own application page, Job Agent detects the ATS and handles it automatically:

| ATS | Detection | Capabilities |
|-----|-----------|-------------|
| **Greenhouse** | `boards.greenhouse.io` | Resume upload, field filling, submit |
| **Lever** | `jobs.lever.co` | Resume upload, field filling, hCaptcha detection |
| **Workday** | `myworkdayjobs.com` | Resume upload, multi-step form navigation |
| **Ashby** | `jobs.ashbyhq.com` | Resume upload, field filling, submit |
| **Generic** | Any form with file upload | AI-powered field detection, resume upload, screening questions |
| **Email Apply** | `mailto:` links or email-only pages | Sends resume + cover letter via SMTP |

Screening questions (multiple choice, dropdowns, free text) are answered automatically using AI based on your profile.

## Project Structure

```
job-agent/
├── config/
│   ├── default.yaml         # System defaults (rate limits, scheduling, browser)
│   ├── profiles/            # Job search profiles (YAML)
│   └── resumes/             # Master resume templates (PDF/MD)
├── src/job_agent/
│   ├── ai/                  # AI client, matching, resume tailoring, cover letters,
│   │                        #   screening question answerer, cold email generator,
│   │                        #   CV-to-profile generator
│   ├── browser/             # Playwright/Camoufox: manager, stealth, humanizer, auth
│   ├── dashboard/           # Flask web UI: routes, templates, static assets
│   ├── db/                  # SQLAlchemy models, session management, repositories
│   ├── notifications/       # Email (SMTP) and webhook (Slack/Discord) notifiers
│   ├── orchestrator/        # Pipeline engine, scheduler, review queue manager
│   ├── platforms/           # Platform drivers:
│   │   ├── linkedin/        #   Discovery + Easy Apply + external redirect
│   │   ├── indeed/          #   Discovery + Easy Apply + external redirect
│   │   ├── glassdoor/       #   Discovery + Easy Apply + external redirect
│   │   ├── ziprecruiter/    #   Discovery + application
│   │   ├── dice/            #   Discovery + application
│   │   ├── wellfound/       #   Discovery + application
│   │   └── external_ats.py  #   Greenhouse, Lever, Workday, Ashby, generic, email
│   └── utils/               # Crypto, logging, rate limiter
└── tests/                   # Unit and integration tests
```

## Security

- Platform credentials are Fernet-encrypted, key stored at `~/.job-agent/fernet.key` (0600 perms)
- API keys live in `.env` (gitignored) or are set via the dashboard
- Database at `~/.job-agent/agent.db` (SQLite, outside repo)
- Browser state at `~/.job-agent/browser_state/` (cookies, localStorage)
- All sensitive data is stored outside the repo directory

## Testing

```bash
uv run pytest tests/ -v
```

## License

MIT
