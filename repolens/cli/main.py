"""Repolens CLI — entry point for all commands."""

from typing import Optional

import typer

app = typer.Typer(
    name="repolens",
    help="AI-powered repository analysis and context engine.",
    add_completion=False,
)


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to the repository to ingest."),
    name: Optional[str] = typer.Option(None, "--name", help="Human-readable repo name."),
    ignore: Optional[list[str]] = typer.Option(None, "--ignore", help="Extra ignore patterns."),
) -> None:
    """Register a repository and run initial scan + classification."""
    typer.echo(f"[stub] ingest {path}")


@app.command()
def scan(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
) -> None:
    """Re-scan an already-registered repository."""
    typer.echo(f"[stub] scan {repo}")


@app.command()
def classify(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
) -> None:
    """Re-run classification and scoring on all files."""
    typer.echo(f"[stub] classify {repo}")


@app.command()
def summarize(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
    scope: str = typer.Option("all", "--scope", help="file|dir|repo|all"),
    force: bool = typer.Option(False, "--force", help="Regenerate even if cached."),
) -> None:
    """Generate AI summaries at file, directory, and/or repo level."""
    typer.echo(f"[stub] summarize {repo} --scope {scope}")


@app.command()
def context(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
    task: str = typer.Option(..., "--task", help="Task type: analyze|summarize|refactor-prep"),
    budget: int = typer.Option(32000, "--budget", help="Token budget."),
    output: Optional[str] = typer.Option(None, "--output", help="Write to file instead of stdout."),
    fmt: str = typer.Option("markdown", "--format", help="markdown|json"),
) -> None:
    """Build a context bundle and write to stdout or file."""
    typer.echo(f"[stub] context {repo} --task {task} --budget {budget}")


@app.command()
def run(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
    task: str = typer.Option(..., "--task", help="Task type."),
    description: Optional[str] = typer.Option(None, "--description", help="Task description."),
    budget: int = typer.Option(32000, "--budget", help="Token budget."),
    model: Optional[str] = typer.Option(None, "--model", help="Override model."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print estimate without calling AI."),
) -> None:
    """Build context bundle and run an AI task."""
    typer.echo(f"[stub] run {repo} --task {task}")


@app.command()
def status(
    repo: Optional[str] = typer.Argument(None, help="Repo ID, name, or path (omit for all)."),
) -> None:
    """Show repo stats: file count, classification breakdown, summary coverage."""
    typer.echo("[stub] status")


@app.command(name="list")
def list_repos() -> None:
    """List all tracked repositories."""
    typer.echo("[stub] list")


@app.command()
def runs(
    repo: Optional[str] = typer.Argument(None, help="Repo ID, name, or path."),
    limit: int = typer.Option(20, "--limit", help="Number of runs to show."),
) -> None:
    """Show recent AI task runs."""
    typer.echo("[stub] runs")


if __name__ == "__main__":
    app()
