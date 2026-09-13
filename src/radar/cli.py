"""`radar` command-line interface - the operator surface for the POC (FR-12, NFR-08).

Commands:
    radar init-db                 create the local DuckDB database
    radar ingest [--offline]      run the S1 pipeline (seed -> enrich -> events -> store)
    radar status                  what is in the database now, plus the top companies by events
    radar company "<name>"        inspect one company: profile, events and their sources
    radar export [--format ...]   write every table to data/exports/
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from radar.config import get_settings
from radar.ingest.pipeline import run as run_ingest
from radar.storage import Store

app = typer.Typer(add_completion=False, help="Opportunity Detection Radar - external POC")
console = Console()


@app.command("init-db")
def init_db() -> None:
    """Create the local analytical database and its schema."""
    settings = get_settings()
    store = Store(settings.resolved_db_path)
    store.close()
    console.print(f"[green]Database ready[/green] at {settings.resolved_db_path}")


@app.command()
def ingest(
    offline: bool = typer.Option(False, "--offline", help="Replay recorded fixtures, no network."),
    live: bool = typer.Option(False, "--live", help="Force live collection from public sources."),
    limit: int | None = typer.Option(None, help="Process only the first N seed companies."),
    record: bool = typer.Option(False, "--record", help="Save live responses as fixtures."),
) -> None:
    """Run the ingestion pipeline."""
    is_offline = offline or (not live)
    settings = get_settings(offline=is_offline, record_fixtures=record)
    mode = "offline (fixtures)" if is_offline else "live (public sources)"
    console.print(f"Running ingest in [bold]{mode}[/bold] mode...")
    report = run_ingest(settings, limit=limit)
    table = Table(title="Ingest report", show_header=False)
    table.add_row("Companies stored", str(report.companies))
    table.add_row("Companies enriched", str(report.enriched))
    table.add_row("Events stored", str(report.events))
    table.add_row("Sources recorded", str(report.sources))
    table.add_row("Dropped (too old)", str(report.dropped_stale))
    table.add_row("Dropped (wrong company)", str(report.dropped_unmatched))
    for connector, n in sorted(report.per_connector.items()):
        table.add_row(f"Candidates from {connector}", str(n))
    console.print(table)


@app.command()
def status() -> None:
    """Show table counts and the companies with the most detected events."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        counts = store.counts()
        table = Table(title="Database contents")
        table.add_column("Table")
        table.add_column("Rows", justify="right")
        for name, n in counts.items():
            table.add_row(name, str(n))
        console.print(table)

        if counts["events"]:
            top = store.df(
                """
                SELECT c.canonical_name AS company, c.country, c.segment,
                       count(*) AS events,
                       count(DISTINCT e.event_type) AS event_types,
                       max(e.event_date) AS latest_event
                FROM events e JOIN companies c USING (company_id)
                GROUP BY 1,2,3 ORDER BY events DESC LIMIT 15
                """
            )
            t2 = Table(title="Top companies by detected events")
            for col in top.columns:
                t2.add_column(col)
            for _, r in top.iterrows():
                t2.add_row(*[str(v) for v in r.tolist()])
            console.print(t2)


@app.command()
def company(name: str) -> None:
    """Inspect one company: profile plus its events and sources."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        prof = store.df(
            "SELECT * FROM companies WHERE lower(canonical_name) LIKE lower(?) LIMIT 1",
            [f"%{name}%"],
        )
        if prof.empty:
            console.print(f"[red]No company matching[/red] {name!r}")
            raise typer.Exit(1)
        row = prof.iloc[0]
        console.print(
            f"[bold]{row['canonical_name']}[/bold]  "
            f"({row['country']} / {row['segment']})"
        )
        console.print(f"  size: {row['size_band']}  listed: {row['listed']}  "
                      f"enrichment: {row['enrichment_confidence']}")
        if row["description"]:
            console.print(f"  {str(row['description'])[:300]}")
        ev = store.df(
            """
            SELECT e.event_date, e.event_type, e.title, e.publisher, s.connector
            FROM events e JOIN sources s USING (source_id)
            WHERE e.company_id = ? ORDER BY e.event_date DESC NULLS LAST LIMIT 25
            """,
            [row["company_id"]],
        )
        if ev.empty:
            console.print("  [dim]no events detected[/dim]")
            return
        t = Table(title=f"Events for {row['canonical_name']}")
        for col in ev.columns:
            t.add_column(col)
        for _, r in ev.iterrows():
            t.add_row(*[str(v)[:70] for v in r.tolist()])
        console.print(t)


@app.command()
def export(fmt: str = typer.Option("csv", "--format", help="csv or parquet")) -> None:
    """Export every table to data/exports/ (FR-12)."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        paths = store.export(settings.exports_dir, fmt=fmt)
    console.print(f"[green]Exported {len(paths)} tables[/green] to {settings.exports_dir}")


if __name__ == "__main__":
    app()
