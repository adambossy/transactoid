from __future__ import annotations

import typer

from scripts import run

app = typer.Typer(help="Transactoid — personal finance agent CLI.")

run_app = typer.Typer(help="Run pipeline workflows.")
app.add_typer(run_app, name="run")

from agents.transactoid import run as transactoid_run


@run_app.command("sync")  # type: ignore[misc]
def run_sync_cmd(
    access_token: str = typer.Option(..., help="Plaid access token for the item"),
    cursor: str | None = typer.Option(
        None, help="Optional cursor for incremental sync"
    ),
    count: int = typer.Option(
        500, help="Maximum number of transactions to fetch per request"
    ),
) -> None:
    """Sync transactions from Plaid and categorize them using an LLM."""
    run.run_sync(access_token=access_token, cursor=cursor, count=count)


@run_app.command("analyzer")  # type: ignore[misc]
def run_analyzer_cmd(
    questions: list[str] | None = typer.Option(  # noqa: B008
        None, help="Optional questions to seed the analyzer session"
    ),
) -> None:
    """Run the analyzer workflow."""
    run.run_analyzer(questions=questions)


@run_app.command("pipeline")  # type: ignore[misc]
def run_pipeline_cmd(
    access_token: str = typer.Option(..., help="Plaid access token for the item"),
    cursor: str | None = typer.Option(
        None, help="Optional cursor for incremental sync"
    ),
    count: int = typer.Option(
        500, help="Maximum number of transactions to fetch per request"
    ),
    questions: list[str] | None = typer.Option(  # noqa: B008
        None, help="Optional questions for analytics"
    ),
) -> None:
    """Run the full pipeline: sync → categorize → persist."""
    run.run_pipeline(
        access_token=access_token, cursor=cursor, count=count, questions=questions
    )


@app.command("sync")  # type: ignore[misc]
def sync(access_token: str, cursor: str | None = None, count: int = 500) -> None:
    """
    Sync transactions from Plaid and categorize them using an LLM.

    Args:
        access_token: Plaid access token for the item
        cursor: Optional cursor for incremental sync (None for initial sync)
        count: Maximum number of transactions to fetch per request
    """
    return None


@app.command("ask")  # type: ignore[misc]
def ask(question: str) -> None:
    return None


@app.command("recat")  # type: ignore[misc]
def recat(merchant_id: int, to: str) -> None:
    return None


@app.command("tag")  # type: ignore[misc]
def tag(rows: list[int], tags: list[str]) -> None:
    return None


@app.command("init-db")  # type: ignore[misc]
def init_db(url: str | None = None) -> None:
    return None


@app.command("seed-taxonomy")  # type: ignore[misc]
def seed_taxonomy(yaml_path: str = "configs/taxonomy.yaml") -> None:
    return None


@app.command("clear-cache")  # type: ignore[misc]
def clear_cache(namespace: str = "default") -> None:
    return None


def agent() -> None:
    """
    Run the transactoid agent to orchestrate sync → categorize → persist in batches.
    """
    transactoid_run()


def main() -> None:
    app()

