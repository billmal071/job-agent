"""Jinja2 prompt templates for AI operations."""

from __future__ import annotations

from jinja2 import Environment, BaseLoader

_env = Environment(loader=BaseLoader(), autoescape=False)

JOB_MATCH_TEMPLATE = _env.from_string("""\
You are an expert job matching system. Analyze the following job posting against the candidate's profile and provide a detailed match assessment.

## Job Posting
- **Title**: {{ job_title }}
- **Company**: {{ company }}
- **Location**: {{ location }}
- **Description**:
{{ description }}

## Candidate Profile
- **Target Role**: {{ profile_name }}
- **Required Skills**: {{ required_skills | join(', ') }}
- **Preferred Skills**: {{ preferred_skills | join(', ') }}
- **Experience Level**: {{ experience_level }}
- **Remote Preference**: {{ remote_preference }}
- **Minimum Salary**: {{ salary_minimum }}

{% if excluded_companies %}
- **Excluded Companies**: {{ excluded_companies | join(', ') }}
{% endif %}
{% if excluded_keywords %}
- **Excluded Keywords**: {{ excluded_keywords | join(', ') }}
{% endif %}

## Instructions
Respond in the following JSON format ONLY (no markdown, no code fences, no surrounding text):
{
    "score": <float 0.0-1.0>,
    "reasoning": "<2-3 sentence explanation>",
    "matched_skills": ["skill1", "skill2"],
    "missing_skills": ["skill1", "skill2"],
    "role_fit": "<brief assessment of role alignment>",
    "red_flags": ["flag1", "flag2"]
}

## Example Output
{"score": 0.82, "reasoning": "Strong match on backend skills. Missing React experience but has similar frontend frameworks.", "matched_skills": ["Python", "Django", "PostgreSQL", "Docker"], "missing_skills": ["React"], "role_fit": "Good fit for mid-level backend with some full-stack overlap", "red_flags": []}

Scoring guide:
- 0.90-1.00: Excellent match, all required skills, strong alignment
- 0.70-0.89: Good match, most required skills, some gaps
- 0.50-0.69: Partial match, significant gaps
- 0.00-0.49: Poor match, major misalignment

Consider: skill match, experience level fit, location/remote compatibility, salary alignment, company exclusions, keyword exclusions.
If the company is in the excluded list or description contains excluded keywords, score should be 0.0.
""")

RESUME_TAILOR_TEMPLATE = _env.from_string("""\
You are an expert resume writer and ATS optimization specialist.

## Task
Tailor the following master resume for the specific job posting below. Optimize for ATS keyword matching while maintaining authenticity.

## Master Resume
{{ master_resume }}

## Target Job
- **Title**: {{ job_title }}
- **Company**: {{ company }}
- **Description**:
{{ description }}

## Key Skills to Emphasize
{{ key_skills | join(', ') }}

## Instructions
1. Output the tailored resume in clean Markdown. Output ONLY the resume, nothing else.
2. Use keywords from the job description naturally in the summary and bullet points.
3. Keep ALL factual information — do NOT remove any roles, projects, education, or certifications.
4. PRESERVE ALL LINKS using markdown syntax: [Email Address](mailto:...) | [Portfolio](https://...) | [LinkedIn](https://...) | [GitHub](https://...)
5. Keep the EXACT same section structure as the master resume: PROFESSIONAL SUMMARY, SKILLS, PROFESSIONAL EXPERIENCE, EARLY CAREER, PROJECTS, EDUCATION/CERTIFICATIONS.

## Formatting Rules (follow exactly)
- Name as `# MALACHY WILLIAMS CHUKWUEBUKA`
- Contact line: `Remote | +234-810-7306-387 | [williams.c.malachy@gmail.com](mailto:...) | [Portfolio](https://...) | [LinkedIn](https://...) | [GitHub](https://...)`
- IMPORTANT: Link labels must be human-readable — use the actual email address, not "Email Address". Use "Portfolio", "LinkedIn", "GitHub" as labels (these are fine since they're recognizable).
- Section headings as `## SECTION NAME`
- Each role as: `### Role | Company | Location | *Date Range*`
- Under each role: a 1-line description paragraph, then bullet points using `- ` (dash space)
- EVERY role from the master resume MUST appear, including the current/present role
- EARLY CAREER as a bullet list with `- ` prefix, one per line
- Education/Certifications as a bullet list, preserving [View Certificate](url) links
- Skills as a bullet list with category labels (e.g. `- **Languages:** Java, TypeScript, ...`)
- Project entries: `### ProjectName | Tech Stack: ... | [View Project](url)`
""")

COVER_LETTER_TEMPLATE = _env.from_string("""\
Write a {{ tone }} cover letter for the following job application.

## Job
- **Title**: {{ job_title }}
- **Company**: {{ company }}
- **Description** (key points):
{{ description[:2000] }}

## Candidate Summary
{{ candidate_summary }}

## Matched Skills
{{ matched_skills | join(', ') }}

## Instructions
- Keep it concise (3-4 paragraphs, under 400 words)
- {{ tone }} tone
- Show enthusiasm for the specific company and role
- Highlight the most relevant matched skills
- Include a clear call to action
- Do NOT fabricate experiences, projects, or accomplishments not present in the candidate summary
- Output ONLY the cover letter text, no headers or formatting instructions
""")

CONNECTION_NOTE_TEMPLATE = _env.from_string("""\
Write a brief LinkedIn connection request note (max 300 characters) to {{ recipient_name }}, {{ recipient_title }} at {{ company }}.

Context: I'm interested in {{ job_title }} opportunities at {{ company }}.

The note should be:
- Personal and genuine
- Reference something specific about the company or role
- Not overly salesy or desperate
- Under 300 characters

Output ONLY the connection note text.
""")

COLD_EMAIL_TEMPLATE = _env.from_string("""\
Write a concise, personalized cold email to {{ recipient_name }}, {{ recipient_title }} at {{ company }}, regarding the {{ job_title }} position.

## Candidate Summary
{{ candidate_summary }}

## Matched Skills
{{ matched_skills | join(', ') }}

## Instructions
- Keep the email brief (3-4 short paragraphs, under 200 words)
- Be professional but personable
- Reference the specific role and company
- Highlight 2-3 most relevant matched skills
- Include a clear but non-pushy call to action
- Do NOT fabricate experiences not in the candidate summary
- Respond in the following JSON format ONLY (no markdown, no code fences):
{"subject": "<email subject line>", "body": "<full email body text>"}
""")

SCREENING_CHOICE_TEMPLATE = _env.from_string("""\
Answer the following job application screening question by selecting the best option.

## Question
{{ question }}

## Available Options
{% for option in options %}- {{ option }}
{% endfor %}

## Candidate Profile
{{ candidate_summary }}

{% if salary_expectation %}- **Salary Expectation**: {{ salary_expectation }}{% endif %}

## Instructions
- You MUST respond with EXACTLY one of the available options listed above
- Do not add any explanation, just the exact option text
- Pick the option that best represents the candidate's qualifications
- If none of the options are a perfect fit, pick the closest match
- Output ONLY the exact option text, nothing else
""")

SCREENING_ANSWER_TEMPLATE = _env.from_string("""\
Answer the following job application screening question based on the candidate's profile.

## Question
{{ question }}

## Candidate Profile
{{ candidate_summary }}

## Instructions
- Answer concisely and honestly
- If it's a yes/no question, answer definitively
- If it asks for years of experience, give a specific number
- If it asks about salary expectations, use {{ salary_expectation }} as a guide
- If the question asks about something not covered in the candidate profile, respond with "N/A"
- Output ONLY the answer text
""")
