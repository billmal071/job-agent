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
        """Convert tailored Markdown resume to PDF. Uses LaTeX if available, else WeasyPrint."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if self.settings.resume.use_latex:
            try:
                return self._generate_latex_pdf(markdown_content, output_path)
            except (FileNotFoundError, OSError) as e:
                log.warning("latex_unavailable_falling_back", error=str(e))

        return self._generate_weasyprint_pdf(markdown_content, output_path)

    def _generate_latex_pdf(self, markdown_content: str, output_path: str) -> str:
        """Generate PDF from Markdown via LaTeX for professional typesetting."""
        import shutil
        import subprocess
        import tempfile

        # Check that pdflatex is installed
        if not shutil.which("pdflatex"):
            raise FileNotFoundError(
                "pdflatex not found. Install a TeX distribution (texlive-latex-recommended) or set resume.use_latex=false."
            )

        latex_content = self._markdown_to_latex(markdown_content)

        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = Path(tmpdir) / "resume.tex"
            tex_path.write_text(latex_content)

            for _ in range(2):  # Run twice for references
                result = subprocess.run(
                    [
                        "pdflatex",
                        "-interaction=nonstopmode",
                        "-output-directory",
                        tmpdir,
                        str(tex_path),
                    ],
                    capture_output=True,
                    timeout=30,
                )

            pdf_generated = Path(tmpdir) / "resume.pdf"
            if not pdf_generated.exists():
                raise OSError(f"pdflatex failed: {result.stderr.decode()[:500]}")

            shutil.copy2(pdf_generated, output_path)

        log.info("resume_latex_pdf_generated", path=output_path)
        return output_path

    def _generate_weasyprint_pdf(self, markdown_content: str, output_path: str) -> str:
        """Fallback: Convert Markdown to PDF using WeasyPrint."""
        from weasyprint import HTML

        html_content = self._markdown_to_html(markdown_content)

        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@400;600&display=swap');

                @page {{
                    size: letter;
                    margin: 0.45in 0.55in;
                }}
                body {{
                    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
                    font-size: 9.5pt;
                    line-height: 1.35;
                    color: #2d2d2d;
                    margin: 0;
                    padding: 0;
                    -webkit-font-smoothing: antialiased;
                }}
                /* Name */
                h1 {{
                    font-family: 'Source Serif 4', 'Georgia', serif;
                    font-size: 20pt;
                    font-weight: 600;
                    margin: 0 0 1pt 0;
                    color: #111;
                    text-align: center;
                    text-transform: uppercase;
                    letter-spacing: 2.5pt;
                }}
                /* Contact line right after name */
                h1 + p {{
                    text-align: center;
                    font-size: 8.5pt;
                    color: #555;
                    margin: 0 0 10pt 0;
                    letter-spacing: 0.3pt;
                    line-height: 1.5;
                }}
                h1 + p a {{
                    color: #555;
                    text-decoration: none;
                    border-bottom: 0.5pt solid #bbb;
                }}
                /* Section headings */
                h2 {{
                    font-size: 9.5pt;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 1.5pt;
                    color: #111;
                    border-bottom: 1.5pt solid #111;
                    padding-bottom: 2pt;
                    margin: 10pt 0 5pt 0;
                }}
                /* Role / subsection headings */
                h3 {{
                    font-size: 9.5pt;
                    font-weight: 600;
                    margin: 6pt 0 1pt 0;
                    color: #1a1a1a;
                    line-height: 1.3;
                }}
                /* Date ranges in role headings */
                h3 em {{
                    font-weight: 400;
                    font-style: normal;
                    color: #666;
                    float: right;
                }}
                ul {{
                    padding-left: 15pt;
                    margin: 1pt 0 4pt 0;
                }}
                li {{
                    margin-bottom: 1pt;
                    text-align: justify;
                    line-height: 1.35;
                }}
                li::marker {{
                    color: #999;
                    font-size: 7pt;
                }}
                p {{
                    margin: 1pt 0;
                    text-align: justify;
                }}
                a {{
                    color: #1a5276;
                    text-decoration: none;
                    border-bottom: 0.5pt solid #a9cce3;
                }}
                strong {{
                    font-weight: 600;
                    color: #1a1a1a;
                }}
                em {{
                    font-style: italic;
                    color: #555;
                }}
                /* Skills section: tighter layout */
                h2 + ul {{
                    margin-top: 3pt;
                }}
                h2 + ul li {{
                    margin-bottom: 0.5pt;
                }}
            </style>
        </head>
        <body>{html_content}</body>
        </html>
        """

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
                f"Master resume not found: {resume_path}. Create it at {resume_path}"
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

    def _markdown_to_latex(self, markdown: str) -> str:
        """Convert Markdown resume to a LaTeX document."""
        import re

        lines = markdown.strip().split("\n")
        tex_lines = [
            r"\documentclass[10pt,letterpaper]{article}",
            r"\usepackage[margin=0.5in]{geometry}",
            r"\usepackage{enumitem}",
            r"\usepackage{titlesec}",
            r"\usepackage[hidelinks]{hyperref}",
            r"\usepackage{xcolor}",
            r"\usepackage{fontenc}",
            r"\pagestyle{empty}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\parskip}{2pt}",
            r"\titleformat{\section}{\large\bfseries\uppercase}{}{0em}{}[\titlerule]",
            r"\titlespacing{\section}{0pt}{8pt}{4pt}",
            r"\titleformat{\subsection}{\normalsize\bfseries}{}{0em}{}",
            r"\titlespacing{\subsection}{0pt}{6pt}{2pt}",
            r"\setlist[itemize]{nosep, leftmargin=14pt, topsep=2pt}",
            r"\begin{document}",
        ]

        in_list = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_list:
                    tex_lines.append(r"\end{itemize}")
                    in_list = False
                continue

            # Escape LaTeX special chars (except in commands we generate)
            def _escape(text: str) -> str:
                text = text.replace("&", r"\&")
                text = text.replace("%", r"\%")
                text = text.replace("$", r"\$")
                text = text.replace("#", r"\#")
                text = text.replace("_", r"\_")
                text = text.replace("~", r"\textasciitilde{}")
                # Convert markdown links to LaTeX hyperlinks
                text = re.sub(
                    r"\[(.+?)\]\((.+?)\)",
                    r"\\href{\2}{\1}",
                    text,
                )
                # Bold
                text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
                # Italic
                text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
                return text

            # Headers
            if stripped.startswith("# "):
                if in_list:
                    tex_lines.append(r"\end{itemize}")
                    in_list = False
                name = _escape(stripped[2:])
                tex_lines.append(r"\begin{center}")
                tex_lines.append(r"{\LARGE\bfseries " + name + r"}")
                tex_lines.append(r"\end{center}")
            elif stripped.startswith("## "):
                if in_list:
                    tex_lines.append(r"\end{itemize}")
                    in_list = False
                heading = _escape(stripped[3:])
                tex_lines.append(r"\section*{" + heading + r"}")
            elif stripped.startswith("### "):
                if in_list:
                    tex_lines.append(r"\end{itemize}")
                    in_list = False
                subheading = _escape(stripped[4:])
                tex_lines.append(r"\subsection*{" + subheading + r"}")
            elif re.match(r"^[-*•+] ", stripped):
                if not in_list:
                    tex_lines.append(r"\begin{itemize}")
                    in_list = True
                item_text = _escape(re.sub(r"^[-*•+] ", "", stripped))
                tex_lines.append(r"\item " + item_text)
            else:
                if in_list:
                    tex_lines.append(r"\end{itemize}")
                    in_list = False
                tex_lines.append(_escape(stripped) + r"\\")

        if in_list:
            tex_lines.append(r"\end{itemize}")

        tex_lines.append(r"\end{document}")
        return "\n".join(tex_lines)

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
