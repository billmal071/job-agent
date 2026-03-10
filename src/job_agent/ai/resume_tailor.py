"""Tailor CVs per job and generate PDF."""

from __future__ import annotations

from pathlib import Path

from job_agent.ai.client import AIClient
from job_agent.ai.prompts import RESUME_TAILOR_TEMPLATE
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class ResumeTailor:
    """Tailors a master resume for specific job postings."""

    def __init__(self, ai_client: AIClient, settings: Settings):
        self.ai = ai_client
        self.settings = settings

    def tailor(
        self,
        job: JobPosting,
        key_skills: list[str],
        master_resume: str | None = None,
    ) -> str:
        """Generate a tailored resume in Markdown format."""
        if master_resume is None:
            master_resume = self._load_master_resume()

        prompt = RESUME_TAILOR_TEMPLATE.render(
            master_resume=master_resume,
            job_title=job.title,
            company=job.company,
            description=job.description[:6000],
            key_skills=key_skills,
        )

        tailored = self.ai.complete(
            prompt=prompt,
            system="You are an expert resume writer. Output clean Markdown only.",
            max_tokens=4096,
            temperature=0.3,
        )

        log.info("resume_tailored", job_id=job.external_id, company=job.company)
        return tailored

    def generate_pdf(self, markdown_content: str, output_path: str) -> str:
        """Convert tailored Markdown resume to PDF using weasyprint."""
        from weasyprint import HTML

        html_content = self._markdown_to_html(markdown_content)

        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                @page {{
                    size: letter;
                    margin: 0.5in 0.6in;
                }}
                body {{
                    font-family: 'Helvetica Neue', Arial, sans-serif;
                    font-size: 10pt;
                    line-height: 1.4;
                    color: #333;
                    margin: 0;
                    padding: 0;
                }}
                h1 {{
                    font-size: 16pt;
                    margin: 0 0 2pt 0;
                    color: #1a1a1a;
                    text-align: center;
                    text-transform: uppercase;
                    letter-spacing: 1pt;
                }}
                /* Contact line right after h1 */
                h1 + p {{
                    text-align: center;
                    font-size: 9pt;
                    color: #555;
                    margin: 0 0 8pt 0;
                }}
                h2 {{
                    font-size: 11pt;
                    text-transform: uppercase;
                    border-bottom: 1.5px solid #333;
                    padding-bottom: 2pt;
                    margin: 12pt 0 6pt 0;
                    color: #1a1a1a;
                    letter-spacing: 0.5pt;
                }}
                h3 {{
                    font-size: 10pt;
                    margin: 8pt 0 2pt 0;
                    color: #1a1a1a;
                }}
                ul {{
                    padding-left: 18pt;
                    margin: 2pt 0 6pt 0;
                }}
                li {{
                    margin-bottom: 1.5pt;
                    text-align: justify;
                }}
                p {{
                    margin: 2pt 0;
                    text-align: justify;
                }}
                a {{
                    color: #0066cc;
                    text-decoration: underline;
                }}
                strong {{
                    color: #1a1a1a;
                }}
                em {{
                    font-style: italic;
                    color: #555;
                }}
            </style>
        </head>
        <body>{html_content}</body>
        </html>
        """

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        HTML(string=styled_html).write_pdf(output_path)
        log.info("resume_pdf_generated", path=output_path)
        return output_path

    def tailor_and_save(
        self,
        job: JobPosting,
        key_skills: list[str],
        output_dir: str | None = None,
    ) -> str:
        """Tailor resume and save as PDF. Returns the PDF path."""
        if output_dir is None:
            output_dir = str(self.settings.data_dir / "resumes")

        tailored_md = self.tailor(job, key_skills)
        safe_name = f"{job.company}_{job.external_id}".replace(" ", "_")[:60]
        pdf_path = f"{output_dir}/{safe_name}.pdf"

        return self.generate_pdf(tailored_md, pdf_path)

    def _load_master_resume(self) -> str:
        """Load the master resume from config (supports .md and .pdf)."""
        resume_path = Path(self.settings.resume.master_resume)
        if not resume_path.exists():
            raise FileNotFoundError(
                f"Master resume not found: {resume_path}. "
                f"Create it at {resume_path}"
            )
        if resume_path.suffix.lower() == ".pdf":
            import pymupdf
            doc = pymupdf.open(str(resume_path))
            text = "\n".join(page.get_text() for page in doc)

            # Extract hyperlinks and append as reference
            links: list[str] = []
            for page in doc:
                for link in page.get_links():
                    if "uri" in link:
                        label = page.get_text("text", clip=link["from"]).strip()
                        if label and link["uri"]:
                            links.append(f"- {label}: {link['uri']}")
            doc.close()

            if links:
                text += "\n\n## Links (use these exact URLs in the tailored resume)\n"
                text += "\n".join(links)

            return text
        return resume_path.read_text()

    def _markdown_to_html(self, markdown: str) -> str:
        """Simple Markdown to HTML conversion."""
        import re

        html = markdown

        # Headers
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

        # Bold and italic
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

        # Links
        html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)

        # List items (- or * or • or +)
        html = re.sub(r"^[-*•+] (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
        # Remove empty bullet lines
        html = re.sub(r"^[-*•+]\s*$", "", html, flags=re.MULTILINE)

        # Wrap consecutive list items in <ul>
        html = re.sub(
            r"(<li>.+?</li>\n?)+",
            lambda m: f"<ul>{m.group()}</ul>",
            html,
        )

        # Paragraphs (lines not already tagged)
        lines = html.split("\n")
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("<"):
                result.append(f"<p>{stripped}</p>")
            else:
                result.append(line)

        return "\n".join(result)
