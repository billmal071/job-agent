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
Respond in the following JSON format ONLY (no markdown, no code fences):
{
    "score": <float 0.0-1.0>,
    "reasoning": "<2-3 sentence explanation>",
    "matched_skills": ["skill1", "skill2"],
    "missing_skills": ["skill1", "skill2"],
    "role_fit": "<brief assessment of role alignment>",
    "red_flags": ["flag1", "flag2"]
}

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
1. Rewrite the resume in Markdown format
2. Emphasize skills and experiences that match the job description
3. Use keywords from the job description naturally throughout
4. Keep the same factual information - only reword and reorganize
5. Ensure ATS-friendly formatting (clear sections, standard headings)
6. Output ONLY the tailored resume in Markdown format, nothing else
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
- Output ONLY the answer text
""")
