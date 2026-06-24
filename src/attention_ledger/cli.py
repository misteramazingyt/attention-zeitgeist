"""Command-line interface for the attention ledger.

Implements the commands described in the spec:

    attention-ledger init
    attention-ledger ingest wikimedia|reddit|gdelt|tranco|cloudflare|commoncrawl ...
    attention-ledger build daily
    attention-ledger classify domains|wikipedia|reddit
    attention-ledger export --format csv --out data/exports/
    attention-ledger dashboard

Each ingest command stores raw payloads, writes normalized events, records the
run in ``ingestion_runs``, and refreshes the ``domains`` table.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from .config import get_config
from .exports import export_tables
from .schemas import AttentionEvent
from .sources import cloudflare, commoncrawl, gdelt, reddit, tranco, wikimedia
from .storage import Storage
from .transforms.aggregate_attention import build_domain_daily, build_topic_daily
from .transforms.classify_topics import (
    classify_domains,
    classify_reddit,
    classify_wikipedia,
)
from .transforms.normalize_domains import normalize_domains
from .transforms.score_attention import build_attention_index
from .utils.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(
    help="Civilizational Attention Ledger: a local-first attention research pipeline.",
    no_args_is_help=True,
    add_completion=False,
)
ingest_app = typer.Typer(help="Ingest data from a source.", no_args_is_help=True)
build_app = typer.Typer(help="Build aggregate and index tables.", no_args_is_help=True)
classify_app = typer.Typer(help="Classify entities into topics/categories.", no_args_is_help=True)
app.add_typer(ingest_app, name="ingest")
app.add_typer(build_app, name="build")
app.add_typer(classify_app, name="classify")


def _persist(source: str, events: list[AttentionEvent], parameters: str) -> int:
    """Write events, refresh domains, and record the ingestion run.

    Returns:
        The number of events written.
    """
    started = datetime.now()
    with Storage() as storage:
        storage.init_schema()
        n = storage.append_events(events)
        storage.upsert_domains_from_events()
        storage.record_run(
            source=source,
            started_at=started,
            finished_at=datetime.now(),
            rows_written=n,
            parameters=parameters,
        )
    typer.echo(f"[{source}] wrote {n} events ({parameters})")
    return n


# --- init ------------------------------------------------------------------
@app.command()
def init() -> None:
    """Create the DuckDB database, data directories, and schema."""
    cfg = get_config()
    cfg.ensure_dirs()
    with Storage() as storage:
        storage.init_schema()
    typer.echo(f"Initialized database at {cfg.db_path}")


# --- ingest ----------------------------------------------------------------
@ingest_app.command("wikimedia")
def ingest_wikimedia(
    start: str = typer.Option(..., help="Start date YYYY-MM-DD (inclusive)."),
    end: str = typer.Option(..., help="End date YYYY-MM-DD (inclusive)."),
    project: Optional[str] = typer.Option(None, help="Wikimedia project, e.g. en.wikipedia."),
    access: str = typer.Option("all-access", help="all-access|desktop|mobile-web|mobile-app."),
) -> None:
    """Ingest Wikimedia top pageviews (pageview_attention)."""
    events = wikimedia.ingest(start=start, end=end, project=project, access=access)
    _persist("wikimedia", events, f"start={start} end={end} project={project or 'default'}")


@ingest_app.command("gdelt")
def ingest_gdelt(
    start: str = typer.Option(..., help="Start date YYYY-MM-DD (inclusive)."),
    end: str = typer.Option(..., help="End date YYYY-MM-DD (inclusive)."),
    query: str = typer.Option(..., help='GDELT query, e.g. "AI OR artificial intelligence".'),
) -> None:
    """Ingest GDELT news articles (news_attention)."""
    events = gdelt.ingest(start=start, end=end, query=query)
    _persist("gdelt", events, f"start={start} end={end} query={query!r}")


@ingest_app.command("tranco")
def ingest_tranco(
    input: Optional[str] = typer.Option(None, help="Path to Tranco CSV (rank,domain)."),
    as_of: Optional[str] = typer.Option(None, help="Snapshot date YYYY-MM-DD (default: today)."),
    demo: bool = typer.Option(False, help="Generate a built-in demo list if input is absent."),
) -> None:
    """Ingest a Tranco ranked-domain list (rank_attention)."""
    events = tranco.ingest(input_path=input, as_of=as_of, demo=demo)
    _persist("tranco", events, f"input={input or 'demo'} as_of={as_of or 'today'}")


@ingest_app.command("cloudflare")
def ingest_cloudflare(
    input: str = typer.Option(..., help="Path to a Cloudflare Radar CSV export."),
    as_of: Optional[str] = typer.Option(None, help="Snapshot date YYYY-MM-DD (default: today)."),
) -> None:
    """Ingest a Cloudflare Radar domain ranking (rank_attention)."""
    events = cloudflare.ingest(input_path=input, as_of=as_of)
    _persist("cloudflare", events, f"input={input} as_of={as_of or 'today'}")


@ingest_app.command("reddit")
def ingest_reddit(
    input: str = typer.Option(..., help="Path to a Reddit dump (.jsonl/.jsonl.zst/.csv/.parquet)."),
) -> None:
    """Ingest a Reddit dump (discursive_attention)."""
    events = reddit.ingest(input_path=input)
    _persist("reddit", events, f"input={input}")


@ingest_app.command("commoncrawl")
def ingest_commoncrawl(
    input: str = typer.Option(..., help="Path to a Common Crawl domain-ranks file (.txt/.gz)."),
    as_of: Optional[str] = typer.Option(None, help="Snapshot date YYYY-MM-DD (default: today)."),
    limit: int = typer.Option(100_000, help="Max number of top domains to ingest."),
) -> None:
    """Ingest a Common Crawl web-graph ranks file (structural_attention)."""
    events = commoncrawl.ingest(input_path=input, as_of=as_of, limit=limit)
    _persist("commoncrawl", events, f"input={input} limit={limit}")


# --- classify --------------------------------------------------------------
@classify_app.command("domains")
def classify_domains_cmd() -> None:
    """Classify domains into categories and platform labels (rule-based)."""
    with Storage() as storage:
        storage.init_schema()
        normalize_domains(storage)
        n = classify_domains(storage)
    typer.echo(f"Classified {n} domains")


@classify_app.command("wikipedia")
def classify_wikipedia_cmd() -> None:
    """Classify Wikipedia article entities into topics/categories."""
    with Storage() as storage:
        storage.init_schema()
        n = classify_wikipedia(storage)
    typer.echo(f"Classified {n} Wikipedia articles")


@classify_app.command("reddit")
def classify_reddit_cmd() -> None:
    """Classify subreddit entities into topics/categories."""
    with Storage() as storage:
        storage.init_schema()
        n = classify_reddit(storage)
    typer.echo(f"Classified {n} subreddits")


# --- build -----------------------------------------------------------------
@build_app.command("daily")
def build_daily() -> None:
    """Build domain_daily, topic_daily, and attention_index_daily."""
    with Storage() as storage:
        storage.init_schema()
        normalize_domains(storage)
        d = build_domain_daily(storage)
        t = build_topic_daily(storage)
        i = build_attention_index(storage)
    typer.echo(f"Built domain_daily={d}, topic_daily={t}, attention_index_daily={i}")


# --- export ----------------------------------------------------------------
@app.command()
def export(
    format: str = typer.Option("csv", help="Export format: csv or parquet."),
    out: str = typer.Option("data/exports/", help="Output directory."),
) -> None:
    """Export research tables to CSV/Parquet."""
    with Storage() as storage:
        storage.init_schema()
        paths = export_tables(storage, out_dir=out, fmt=format)
    typer.echo(f"Exported {len(paths)} tables to {out}:")
    for p in paths:
        typer.echo(f"  {p}")


# --- dashboard -------------------------------------------------------------
@app.command()
def dashboard(
    port: int = typer.Option(8501, help="Port for the Streamlit server."),
) -> None:
    """Launch the Streamlit dashboard."""
    app_path = Path(__file__).parent / "dashboards" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
    ]
    typer.echo(f"Launching dashboard: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        typer.echo(
            "Streamlit is not installed. Install dashboard extras:\n"
            '  pip install -e ".[dashboard]"',
            err=True,
        )
        raise typer.Exit(code=1)


def main() -> None:
    """Entry point for ``python -m attention_ledger.cli``."""
    app()


if __name__ == "__main__":
    main()
