"""Repolens CLI — entry point for all commands."""

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from repolens import config
from repolens.db.repository import (
    create_repo,
    get_repo,
    list_repos as db_list_repos,
    upsert_file,
)
from repolens.db.schema import init_db
from repolens.ingestion.scanner import scan_repo

app = typer.Typer(
    name="repolens",
    help="AI-powered repository analysis and context engine.",
    add_completion=False,
)


def _open_conn() -> sqlite3.Connection:
    """Open a connection to the configured DB with row_factory set."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to the repository to ingest."),
    name: Optional[str] = typer.Option(None, "--name", help="Human-readable repo name."),
    ignore: Optional[list[str]] = typer.Option(None, "--ignore", help="Extra ignore patterns."),
) -> None:
    """Register a repository and scan all text files into the DB."""
    abs_path = Path(path).resolve()
    if not abs_path.exists():
        typer.echo(f"Error: path does not exist: {abs_path}", err=True)
        raise typer.Exit(1)
    if not abs_path.is_dir():
        typer.echo(f"Error: path is not a directory: {abs_path}", err=True)
        raise typer.Exit(1)

    init_db()
    conn = _open_conn()
    try:
        # Create or reuse existing repo record
        existing = get_repo(conn, str(abs_path))
        if existing is None:
            repo_name = name or abs_path.name
            repo_id = create_repo(conn, str(abs_path), repo_name)
        else:
            repo_id = existing["id"]
            repo_name = existing["name"]

        custom_ignores = list(ignore) if ignore else []
        records = scan_repo(str(abs_path), custom_ignores)

        # Quick total-file count for skipped calculation (all regular files, no filter)
        total_files = sum(
            len(files)
            for _, _, files in os.walk(str(abs_path))
        )
        skipped = total_files - len(records)

        # Upsert every scanned file
        for rec in records:
            upsert_file(
                conn,
                repo_id,
                rec.relative_path,
                extension=rec.extension,
                size_bytes=rec.size_bytes,
                mtime=rec.mtime,
                content_hash=rec.content_hash,
            )

        # Refresh repo-level aggregate stats
        now = int(time.time())
        total_size = sum(r.size_bytes for r in records)
        with conn:
            conn.execute(
                """
                UPDATE repos
                SET file_count = ?,
                    total_size_bytes = ?,
                    last_scanned_at = ?,
                    ingested_at = COALESCE(ingested_at, ?)
                WHERE id = ?
                """,
                (len(records), total_size, now, now, repo_id),
            )
    finally:
        conn.close()

    typer.echo(
        f"Ingested {repo_name}: {len(records)} files scanned, {skipped} skipped"
    )


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
    init_db()
    conn = _open_conn()
    try:
        repos = db_list_repos(conn)
    finally:
        conn.close()

    if not repos:
        typer.echo("No repositories tracked yet.")
        return

    # Column widths
    id_w, name_w, path_w, files_w, scan_w = 4, 24, 48, 6, 19

    header = (
        f"{'ID':<{id_w}}  {'Name':<{name_w}}  {'Path':<{path_w}}  "
        f"{'Files':>{files_w}}  {'Last scanned':<{scan_w}}"
    )
    typer.echo(header)
    typer.echo("-" * len(header))

    for r in repos:
        last_ts = r.get("last_scanned_at")
        last = (
            datetime.fromtimestamp(last_ts).strftime("%Y-%m-%d %H:%M")
            if last_ts
            else "never"
        )
        file_count = r.get("file_count") or 0
        typer.echo(
            f"{r['id']:<{id_w}}  {r['name']:<{name_w}}  {r['path']:<{path_w}}  "
            f"{file_count:>{files_w}}  {last:<{scan_w}}"
        )


@app.command()
def runs(
    repo: Optional[str] = typer.Argument(None, help="Repo ID, name, or path."),
    limit: int = typer.Option(20, "--limit", help="Number of runs to show."),
) -> None:
    """Show recent AI task runs."""
    typer.echo("[stub] runs")


if __name__ == "__main__":
    app()
