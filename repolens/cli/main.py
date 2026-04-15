"""Repolens CLI — entry point for all commands."""

import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from repolens import config
from repolens.ai.client import RepolensClient
from repolens.classification.classifier import classify_file, score_file
from repolens.context.token_counter import estimate_cost
from repolens.context.exporter import export_json, export_markdown
from repolens.context.packager import build_context
from repolens.db.repository import (
    create_repo,
    get_repo,
    list_files,
    list_repos as db_list_repos,
    list_summaries_by_scope,
    save_bundle,
    upsert_file,
)
from repolens.db.schema import init_db
from repolens.ingestion.scanner import FileRecord, scan_repo
from repolens.summarization.dir_summarizer import summarize_directory
from repolens.summarization.file_summarizer import summarize_file
from repolens.summarization.repo_summarizer import summarize_repo

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


def _resolve_repo(conn: sqlite3.Connection, repo: str) -> dict:
    """Resolve a repo argument (int ID, name, or path) to a repo row.

    Tries integer ID first, then falls back to path/name lookup via get_repo.
    Exits with an error message if not found.
    """
    # Try int ID
    try:
        repo_id = int(repo)
        row = get_repo(conn, repo_id)
    except ValueError:
        row = None

    # Fall back to path/name lookup
    if row is None:
        row = get_repo(conn, repo)

    if row is None:
        typer.echo(f"Error: repository not found: {repo!r}", err=True)
        typer.echo("Run 'repolens list' to see tracked repositories.", err=True)
        raise typer.Exit(1)

    return dict(row)


@app.command()
def classify(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
) -> None:
    """Classify and score every file in a repository."""
    init_db()
    conn = _open_conn()
    try:
        repo_row = _resolve_repo(conn, repo)
        repo_id: int = repo_row["id"]
        repo_name: str = repo_row["name"]

        files = list_files(conn, repo_id)
        if not files:
            typer.echo(f"No files found for repo {repo_name!r}. Run 'repolens ingest' first.")
            return

        category_counts: dict[str, int] = {}
        scored: list[tuple[float, str]] = []

        for f in files:
            relative_path: str = f["path"]
            extension: str = f.get("extension") or ""
            size_bytes: int = f.get("size_bytes") or 0
            mtime: int = f.get("mtime") or 0

            category = classify_file(relative_path, extension)
            score = score_file(relative_path, category, size_bytes, mtime)

            upsert_file(
                conn,
                repo_id,
                relative_path,
                classification=category,
                importance_score=score,
            )

            category_counts[category] = category_counts.get(category, 0) + 1
            scored.append((score, relative_path))

    finally:
        conn.close()

    total = len(scored)
    typer.echo(f"\nClassified {total} files in {repo_name!r}\n")

    typer.echo("Category breakdown:")
    for cat in ("core", "config", "test", "docs", "build", "generated", "other"):
        count = category_counts.get(cat, 0)
        if count:
            bar = "#" * min(count, 40)
            typer.echo(f"  {cat:<12} {count:>4}  {bar}")

    top5 = sorted(scored, key=lambda x: x[0], reverse=True)[:5]
    typer.echo("\nTop 5 files by importance score:")
    for score, path in top5:
        typer.echo(f"  {score:.4f}  {path}")


@app.command()
def summarize(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
    scope: str = typer.Option("all", "--scope", help="file|dir|repo|all"),
    force: bool = typer.Option(False, "--force", help="Regenerate even if cached."),
) -> None:
    """Generate AI summaries at file, directory, and/or repo level."""
    valid_scopes = {"file", "dir", "repo", "all"}
    if scope not in valid_scopes:
        typer.echo(
            f"Error: --scope must be one of: {', '.join(sorted(valid_scopes))}",
            err=True,
        )
        raise typer.Exit(1)

    init_db()
    conn = _open_conn()
    try:
        repo_row = _resolve_repo(conn, repo)
        repo_id: int = repo_row["id"]
        repo_root: str = repo_row["path"]

        # --force: delete cached summaries so all levels get regenerated
        if force:
            with conn:
                if scope in ("file", "all"):
                    conn.execute(
                        "DELETE FROM summaries WHERE repo_id = ? AND scope = 'file'",
                        (repo_id,),
                    )
                if scope in ("dir", "all"):
                    conn.execute(
                        "DELETE FROM summaries WHERE repo_id = ? AND scope = 'directory'",
                        (repo_id,),
                    )
                if scope in ("repo", "all"):
                    conn.execute(
                        "DELETE FROM summaries WHERE repo_id = ? AND scope = 'repo'",
                        (repo_id,),
                    )

        # Instantiate AI client — raises ValueError if ANTHROPIC_API_KEY is missing
        try:
            client = RepolensClient()
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1)

        # Track tokens across all API calls by wrapping client.complete()
        total_prompt_tokens = 0
        total_completion_tokens = 0
        _orig_complete = client.complete

        def _tracking_complete(prompt: str) -> tuple[str, int, int]:
            nonlocal total_prompt_tokens, total_completion_tokens
            result = _orig_complete(prompt)
            total_prompt_tokens += result[1]
            total_completion_tokens += result[2]
            return result

        client.complete = _tracking_complete  # type: ignore[method-assign]

        # ------------------------------------------------------------------
        # File-level summaries
        # ------------------------------------------------------------------
        file_summaries: dict[str, str] = {}

        if scope in ("file", "all"):
            files = list_files(conn, repo_id)
            if not files:
                typer.echo(
                    "No files found. Run 'repolens ingest' first.", err=True
                )
                raise typer.Exit(1)

            for f in files:
                rel_path: str = f["path"]
                typer.echo(f"Summarizing file: {rel_path}")
                file_record = FileRecord(
                    repo_root=repo_root,
                    relative_path=rel_path,
                    extension=f.get("extension") or "",
                    size_bytes=f.get("size_bytes") or 0,
                    mtime=f.get("mtime") or 0,
                    content_hash=f.get("content_hash") or "",
                )
                summary = summarize_file(conn, repo_id, file_record, client)
                file_summaries[rel_path] = summary
        else:
            # Load pre-existing file summaries for dir/repo-only runs
            for row in list_summaries_by_scope(conn, repo_id, "file"):
                file_summaries[row["target_path"]] = row["summary"]

        # ------------------------------------------------------------------
        # Directory-level summaries
        # ------------------------------------------------------------------
        dir_summaries: dict[str, str] = {}

        if scope in ("dir", "all"):
            # Group file summaries by parent directory
            dir_to_files: dict[str, dict[str, str]] = defaultdict(dict)
            for file_path, file_summary in file_summaries.items():
                dir_path = os.path.dirname(file_path)
                dir_to_files[dir_path][file_path] = file_summary

            for dir_path, dir_file_summaries in sorted(dir_to_files.items()):
                display = dir_path if dir_path else "."
                typer.echo(f"Summarizing directory: {display}")
                summary = summarize_directory(
                    conn, repo_id, dir_path, dir_file_summaries, client
                )
                dir_summaries[dir_path] = summary
        else:
            # Load pre-existing directory summaries for repo-only runs
            for row in list_summaries_by_scope(conn, repo_id, "directory"):
                dir_summaries[row["target_path"]] = row["summary"]

        # ------------------------------------------------------------------
        # Repo-level summary
        # ------------------------------------------------------------------
        if scope in ("repo", "all"):
            typer.echo("Summarizing repository...")
            summarize_repo(conn, repo_id, dir_summaries, client)

        # ------------------------------------------------------------------
        # Usage report
        # ------------------------------------------------------------------
        if total_prompt_tokens > 0 or total_completion_tokens > 0:
            cost = estimate_cost(
                total_prompt_tokens, total_completion_tokens, client.model
            )
            typer.echo(
                f"\nTokens used: {total_prompt_tokens} prompt"
                f" + {total_completion_tokens} completion"
            )
            typer.echo(f"Estimated cost: ${cost:.4f}")
        else:
            typer.echo("\nNo API calls made (all summaries served from cache).")

    finally:
        conn.close()


@app.command()
def context(
    repo: str = typer.Argument(..., help="Repo ID, name, or path."),
    task: str = typer.Option(..., "--task", help="Task type: analyze|summarize|refactor-prep"),
    budget: int = typer.Option(32000, "--budget", help="Token budget."),
    output: Optional[str] = typer.Option(None, "--output", help="Write to file instead of stdout."),
    fmt: str = typer.Option("markdown", "--format", help="markdown|json"),
) -> None:
    """Build a context bundle and write to stdout or file."""
    if fmt not in ("markdown", "json"):
        typer.echo(f"Error: --format must be 'markdown' or 'json', got: {fmt!r}", err=True)
        raise typer.Exit(1)

    init_db()
    conn = _open_conn()
    try:
        repo_row = _resolve_repo(conn, repo)
        repo_id: int = repo_row["id"]

        bundle = build_context(conn, repo_id, task, token_budget=budget)

        save_bundle(
            conn,
            repo_id=repo_id,
            task_type=task,
            token_budget=budget,
            token_count=bundle.token_count,
            content=bundle.content,
            file_paths=bundle.file_paths,
        )

        # Stderr: token count + file list (safe to pipe stdout)
        typer.echo(f"token_count: {bundle.token_count}", err=True)
        typer.echo(f"files ({len(bundle.file_paths)}):", err=True)
        for fp in bundle.file_paths:
            typer.echo(f"  {fp}", err=True)

        # Format output
        if fmt == "json":
            formatted = export_json(bundle, task_type=task, repo_id=repo_id)
        else:
            formatted = export_markdown(bundle, task_type=task, repo_id=repo_id)

        if output:
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(formatted, encoding="utf-8")
            typer.echo(f"Written to {output}", err=True)
        else:
            typer.echo(formatted)

    finally:
        conn.close()


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
