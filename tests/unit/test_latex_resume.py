"""Tests for LaTeX resume generation and fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.config import Settings


def _settings(**overrides):
    defaults = dict(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    defaults.update(overrides)
    return Settings(**defaults)


SAMPLE_MD = """\
# John Doe

New York, NY | john@example.com | [LinkedIn](https://linkedin.com/in/johndoe)

## Professional Summary

Experienced software engineer with 10 years of Python development.

## Skills

- **Languages:** Python, JavaScript, TypeScript
- **Frameworks:** Django, FastAPI, React

## Professional Experience

### Senior Developer | Acme Corp | Remote | *2020 - Present*

- Built scalable APIs serving 1M+ requests/day
- Led team of 5 engineers on microservices migration
- Reduced deployment time by 60% with CI/CD pipeline

### Developer | StartupCo | NYC | *2018 - 2020*

- Developed full-stack web application using Django & React
- Implemented automated testing with 95% code coverage

## Education

- B.S. Computer Science, MIT, 2018
"""


def test_markdown_to_latex_produces_valid_structure():
    """LaTeX output contains document structure."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    latex = tailor._markdown_to_latex(SAMPLE_MD)

    assert r"\documentclass" in latex
    assert r"\begin{document}" in latex
    assert r"\end{document}" in latex
    assert r"\section*{" in latex
    assert r"\subsection*{" in latex
    assert r"\begin{itemize}" in latex
    assert r"\item" in latex
    assert "John Doe" in latex


def test_markdown_to_latex_escapes_special_chars():
    """LaTeX special characters are escaped."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    md = "# Test\n\n- Improved performance by 50% & reduced costs $100k"
    latex = tailor._markdown_to_latex(md)

    assert r"\&" in latex
    assert r"\$" in latex
    assert r"\%" in latex


def test_markdown_to_latex_converts_links():
    """Markdown links become LaTeX hyperlinks."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    md = "# Name\n\n[Portfolio](https://example.com)"
    latex = tailor._markdown_to_latex(md)

    assert r"\href{https://example.com}{Portfolio}" in latex


def test_markdown_to_latex_handles_bold_italic():
    """Bold and italic markdown converts to LaTeX commands."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    md = "# Name\n\n- **Languages:** Python, *Java*"
    latex = tailor._markdown_to_latex(md)

    assert r"\textbf{Languages:}" in latex
    assert r"\textit{Java}" in latex


def test_generate_pdf_falls_back_to_weasyprint(tmp_path):
    """When pdflatex is not available, falls back to WeasyPrint."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    output_path = str(tmp_path / "resume.pdf")

    with patch("shutil.which", return_value=None):
        with patch.object(
            tailor, "_generate_weasyprint_pdf", return_value=output_path
        ) as mock_wp:
            result = tailor.generate_pdf(SAMPLE_MD, output_path)
            mock_wp.assert_called_once_with(SAMPLE_MD, output_path)
            assert result == output_path


def test_generate_pdf_uses_latex_when_available(tmp_path):
    """When pdflatex is available, uses LaTeX generation."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    output_path = str(tmp_path / "resume.pdf")

    with patch.object(
        tailor, "_generate_latex_pdf", return_value=output_path
    ) as mock_latex:
        result = tailor.generate_pdf(SAMPLE_MD, output_path)
        mock_latex.assert_called_once_with(SAMPLE_MD, output_path)
        assert result == output_path


def test_generate_pdf_skips_latex_when_disabled(tmp_path):
    """When use_latex is False, goes directly to WeasyPrint."""
    s = _settings()
    s.resume.use_latex = False
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    output_path = str(tmp_path / "resume.pdf")

    with patch.object(
        tailor, "_generate_weasyprint_pdf", return_value=output_path
    ) as mock_wp:
        with patch.object(tailor, "_generate_latex_pdf") as mock_latex:
            tailor.generate_pdf(SAMPLE_MD, output_path)
            mock_latex.assert_not_called()
            mock_wp.assert_called_once()


@patch("shutil.which", return_value="/usr/bin/pdflatex")
@patch("subprocess.run")
def test_generate_latex_pdf_calls_pdflatex(mock_run, mock_which, tmp_path):
    """LaTeX PDF generation calls pdflatex."""
    s = _settings()
    ai = MagicMock()
    tailor = ResumeTailor(ai, s)

    output_path = str(tmp_path / "resume.pdf")

    # Create a fake PDF so the method finds it
    def fake_run(cmd, **kwargs):
        output_dir = cmd[cmd.index("-output-directory") + 1]
        Path(output_dir, "resume.pdf").write_bytes(b"%PDF-1.4 fake")
        return MagicMock(returncode=0, stderr=b"")

    mock_run.side_effect = fake_run

    result = tailor._generate_latex_pdf(SAMPLE_MD, output_path)
    assert result == output_path
    assert Path(output_path).exists()
    assert mock_run.call_count == 2  # Runs twice for references
