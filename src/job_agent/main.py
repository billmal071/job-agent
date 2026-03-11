"""CLI entry point for job-agent."""

from __future__ import annotations

import getpass

import click

from job_agent.config import load_settings
from job_agent.db.models import Platform
from job_agent.db.session import get_session, init_db
from job_agent.utils.crypto import encrypt
from job_agent.utils.logging import setup_logging


@click.group()
@click.option("--config", "-c", default=None, help="Path to config YAML override.")
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
)
@click.pass_context
def cli(ctx: click.Context, config: str | None, log_level: str) -> None:
    """Job Agent - Autonomous job application agent."""
    setup_logging(log_level=log_level)
    ctx.ensure_object(dict)
    ctx.obj["settings"] = load_settings(config)


@cli.command("init-db")
@click.pass_context
def cmd_init_db(ctx: click.Context) -> None:
    """Initialize the database (create all tables)."""
    settings = ctx.obj["settings"]
    init_db(settings)
    click.echo(f"Database initialized at: {settings.db_path}")


@cli.command("add-credential")
@click.argument("platform", type=click.Choice(["linkedin", "indeed", "glassdoor"]))
@click.option("--username", "-u", prompt=True, help="Platform username/email.")
@click.pass_context
def cmd_add_credential(ctx: click.Context, platform: str, username: str) -> None:
    """Store encrypted credentials for a platform."""
    from job_agent.db.repository import CredentialRepository

    password = getpass.getpass("Password: ")
    encrypted = encrypt(password)

    settings = ctx.obj["settings"]
    init_db(settings)
    session = get_session(settings)
    try:
        repo = CredentialRepository(session)
        repo.upsert(
            platform=Platform(platform),
            username=username,
            encrypted_password=encrypted,
        )
        session.commit()
        click.echo(f"Credentials stored for {platform}.")
    finally:
        session.close()


@cli.command("run")
@click.option("--profile", "-p", required=True, help="Path to profile YAML.")
@click.option("--platform", type=click.Choice(["linkedin", "indeed", "glassdoor"]))
@click.option("--dry-run", is_flag=True, help="Discover and match only, don't apply.")
@click.option("--once", is_flag=True, help="Run once instead of on schedule.")
@click.pass_context
def cmd_run(
    ctx: click.Context,
    profile: str,
    platform: str | None,
    dry_run: bool,
    once: bool,
) -> None:
    """Run the job agent pipeline."""
    from job_agent.orchestrator.engine import OrchestratorEngine

    settings = ctx.obj["settings"]
    if dry_run:
        settings.agent.dry_run = True

    init_db(settings)
    engine = OrchestratorEngine(settings)
    if once:
        engine.run_once(profile_path=profile, platform=platform)
    else:
        engine.start(profile_path=profile, platform=platform)


@cli.command("apply-approved")
@click.pass_context
def cmd_apply_approved(ctx: click.Context) -> None:
    """Apply to all approved jobs from the review queue (skips discovery)."""
    from job_agent.orchestrator.pipeline import apply_approved

    settings = ctx.obj["settings"]
    init_db(settings)
    stats = apply_approved(settings)
    click.echo(
        f"Done: {stats['applied']} applied, {stats['failed']} failed, {stats['skipped']} skipped"
    )


@cli.command("search")
@click.option(
    "--platform",
    "-P",
    default="linkedin",
    type=click.Choice(["linkedin", "indeed", "glassdoor"]),
)
@click.option("--query", "-q", required=True, help="Search query.")
@click.option("--location", "-l", default="", help="Location filter.")
@click.option("--limit", "-n", default=25, help="Max results.")
@click.pass_context
def cmd_search(
    ctx: click.Context,
    platform: str,
    query: str,
    location: str,
    limit: int,
) -> None:
    """Search for jobs on a platform (without applying)."""
    click.echo(f"Searching {platform} for: {query}")
    # Imports deferred to avoid circular / heavy imports at startup
    from job_agent.orchestrator.pipeline import discover_jobs

    settings = ctx.obj["settings"]
    init_db(settings)
    jobs = discover_jobs(
        settings=settings,
        platform_name=platform,
        query=query,
        location=location,
        limit=limit,
    )
    click.echo(f"Found {len(jobs)} jobs:")
    for j in jobs:
        click.echo(f"  [{j.platform.value}] {j.title} @ {j.company} - {j.url}")


@cli.command("dashboard")
@click.pass_context
def cmd_dashboard(ctx: click.Context) -> None:
    """Start the web dashboard."""
    from job_agent.dashboard.app import create_app

    settings = ctx.obj["settings"]
    init_db(settings)
    app = create_app(settings)
    app.run(
        host=settings.dashboard.host,
        port=settings.dashboard.port,
        debug=True,
    )


@cli.command("setup")
@click.pass_context
def cmd_setup(ctx: click.Context) -> None:
    """Interactive setup wizard for new users."""
    settings = ctx.obj["settings"]
    click.echo("=== Job Agent Setup Wizard ===\n")

    # Step 1: Init DB
    click.echo("Step 1: Initializing database...")
    init_db(settings)
    click.echo(f"  Database created at: {settings.db_path}\n")

    # Step 2: API key check
    click.echo("Step 2: Checking API key...")
    if settings.anthropic_api_key:
        click.echo("  Anthropic API key found in environment.\n")
    else:
        click.echo("  WARNING: ANTHROPIC_API_KEY not set in .env or environment.")
        click.echo("  Set it before running the agent.\n")

    # Step 3: Add credentials
    if click.confirm("Step 3: Would you like to add platform credentials now?"):
        for p in ["linkedin", "indeed", "glassdoor"]:
            if click.confirm(f"  Add {p} credentials?", default=(p == "linkedin")):
                username = click.prompt(f"    {p} username/email")
                password = getpass.getpass(f"    {p} password: ")
                encrypted = encrypt(password)
                session = get_session(settings)
                try:
                    from job_agent.db.repository import CredentialRepository

                    CredentialRepository(session).upsert(
                        Platform(p), username, encrypted
                    )
                    session.commit()
                    click.echo(f"    {p} credentials saved.\n")
                finally:
                    session.close()

    click.echo("\nSetup complete! Next steps:")
    click.echo(
        "  1. Create a profile: cp config/profiles/example.yaml config/profiles/myprofile.yaml"
    )
    click.echo("  2. Edit the profile with your preferences")
    click.echo("  3. Add your master resume to config/resumes/master.md")
    click.echo("  4. Run: job-agent run --profile config/profiles/myprofile.yaml")
    click.echo("  5. Or start the dashboard: job-agent dashboard")


if __name__ == "__main__":
    cli()
