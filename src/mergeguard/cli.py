"""MergeGuard CLI — `mergeguard review` entrypoint."""

from __future__ import annotations

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler

from mergeguard import __version__
from mergeguard.config import get_config

app = typer.Typer(
    name="mergeguard",
    help="AI PR Code Review Agent powered by AWS Strands SDK and Amazon Bedrock.",
    add_completion=False,
)
feedback_app = typer.Typer(name="feedback", help="Feedback loop commands.")
app.add_typer(feedback_app, name="feedback")
console = Console()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"mergeguard {__version__}")
        raise typer.Exit()


@app.command()
def review(
    pr: str = typer.Option(..., "--pr", help="PR URL or owner/repo#number"),
    config_file: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to .mergeguard.yml"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print review without posting to GitHub."
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose logging."),
) -> None:
    """Run an AI code review on a GitHub Pull Request."""
    cfg = get_config()
    _setup_logging("DEBUG" if verbose else cfg.log_level)
    log = logging.getLogger("mergeguard")

    log.info(f"Starting review for PR: {pr}")
    log.debug(f"Bedrock model: {cfg.bedrock_model_id}")
    log.debug(f"Dry run: {dry_run}")

    # Parse PR reference
    pr_ref = _parse_pr_ref(pr)
    if pr_ref is None:
        console.print(f"[red]Cannot parse PR reference: {pr!r}[/red]")
        raise typer.Exit(1)

    owner, repo, number = pr_ref
    log.info(f"Reviewing {owner}/{repo}#{number}")

    # Lazy import to avoid heavy imports on --help
    from mergeguard.agents.orchestrator import build_orchestrator

    orchestrator = build_orchestrator()
    result = orchestrator(
        f"Review GitHub PR: owner={owner} repo={repo} pr_number={number} "
        f"dry_run={dry_run}"
    )

    console.print(result)


@app.command()
def smoke_test() -> None:
    """Verify Bedrock connectivity (no GitHub needed)."""
    _setup_logging("INFO")
    log = logging.getLogger("mergeguard")
    log.info("Running Bedrock smoke test…")

    from mergeguard.integrations.bedrock import build_model

    model = build_model()
    # Quick single-turn call
    from strands import Agent

    agent = Agent(model=model, system_prompt="You are a helpful assistant.")
    result = agent("Reply with exactly: SMOKE_TEST_OK")
    if "SMOKE_TEST_OK" in str(result):
        console.print("[green]Bedrock smoke test PASSED[/green]")
    else:
        console.print(f"[yellow]Unexpected response: {result}[/yellow]")


def _parse_pr_ref(pr: str) -> tuple[str, str, int] | None:
    """Parse 'owner/repo#123' or a GitHub PR URL into (owner, repo, number)."""
    import re

    # URL form: https://github.com/owner/repo/pull/123
    url_match = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr
    )
    if url_match:
        return url_match.group(1), url_match.group(2), int(url_match.group(3))

    # Short form: owner/repo#123
    short_match = re.match(r"([^/]+)/([^#]+)#(\d+)", pr)
    if short_match:
        return short_match.group(1), short_match.group(2), int(short_match.group(3))

    return None


@feedback_app.command("sync")
def feedback_sync(
    verbose: bool = typer.Option(False, "--verbose", help="Verbose logging."),
) -> None:
    """Poll GitHub reactions on inline review comments and update the feedback store."""
    cfg = get_config()
    _setup_logging("DEBUG" if verbose else cfg.log_level)
    log = logging.getLogger("mergeguard")

    from mergeguard.feedback.s3_sync import download_if_exists, upload
    from mergeguard.feedback.store import get_db_path, open_db
    from mergeguard.integrations.github import get_github_client
    from mergeguard.tools.feedback_sync import sync_reactions

    db_path = get_db_path()
    log.info("Feedback DB: %s", db_path)
    download_if_exists(db_path)
    conn = open_db(db_path)
    gh = get_github_client()
    count = sync_reactions(conn, gh)
    conn.close()
    upload(db_path)
    console.print(f"[green]Synced reactions for {count} inline comment(s).[/green]")


if __name__ == "__main__":
    app()
