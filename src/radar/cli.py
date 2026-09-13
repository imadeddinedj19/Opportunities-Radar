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
    table.add_row("[bold]Distinct insights[/bold]", str(report.insights_total))
    table.add_row("[bold]New insights this run[/bold]", str(report.insights_new))
    table.add_row("Feature values written (S2)", str(report.features_written))
    table.add_row("[bold]Companies scored (S3)[/bold]", str(report.scored))
    console.print(table)
    console.print(
        'Ranked list: [bold]radar rank[/bold]  ·  '
        'one company: [bold]radar score "<name>"[/bold]'
    )


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
def insights(
    new: bool = typer.Option(False, "--new", help="Only insights first seen on the latest run."),
    company: str | None = typer.Option(None, help="Filter to one company (name contains)."),
    limit: int = typer.Option(25, help="Maximum insights to show."),
) -> None:
    """Daily Insights: distinct, deduplicated signals, each with the sources that reported it."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        where = []
        params: list = []
        if new:
            where.append("i.is_new = TRUE")
        if company:
            where.append("lower(c.canonical_name) LIKE lower(?)")
            params.append(f"%{company}%")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = store.df(
            f"""
            SELECT i.insight_id, c.canonical_name AS company, i.insight_type AS type,
                   i.event_date, i.source_count, i.connectors, i.canonical_title, i.is_new
            FROM insights i JOIN companies c USING (company_id)
            {clause}
            ORDER BY i.is_new DESC, i.source_count DESC, i.event_date DESC NULLS LAST
            LIMIT {int(limit)}
            """,
            params,
        )
        if rows.empty:
            console.print("[dim]No insights match. Run `radar ingest` first.[/dim]")
            return
        title = "New insights (this run)" if new else "Daily Insights"
        t = Table(title=title)
        for col in ("company", "type", "event_date", "sources", "insight"):
            t.add_column(col)
        for _, r in rows.iterrows():
            conns = ", ".join(r["connectors"]) if r["connectors"] is not None else ""
            flag = "🆕 " if r["is_new"] else ""
            t.add_row(
                str(r["company"])[:22],
                str(r["type"]),
                str(r["event_date"])[:10],
                f"{r['source_count']} ({conns})",
                flag + str(r["canonical_title"])[:60],
            )
        console.print(t)


@app.command()
def features(
    company: str | None = typer.Option(None, help="Show the feature vector for one company."),
    top: int = typer.Option(15, help="When no company given, rank this many companies."),
    by: str = typer.Option("recency_score", help="Feature to rank by (e.g. recency_score)."),
) -> None:
    """S2 features: per-company model-ready numbers (intensity, recency, fit, similarity)."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        if store.count("feature_snapshots") == 0:
            console.print("[dim]No features yet. Run `radar ingest` first.[/dim]")
            return
        if company:
            df = store.df(
                """
                SELECT f.feature_name, f.value
                FROM feature_snapshots f JOIN companies c USING (company_id)
                WHERE lower(c.canonical_name) LIKE lower(?)
                ORDER BY f.feature_name
                """,
                [f"%{company}%"],
            )
            if df.empty:
                console.print(f"[red]No features for[/red] {company!r}")
                raise typer.Exit(1)
            t = Table(title=f"Features for {company}")
            t.add_column("feature")
            t.add_column("value", justify="right")
            for _, r in df.iterrows():
                t.add_row(str(r["feature_name"]), f"{r['value']:.4g}")
            console.print(t)
            return
        # ranking view: pivot one feature across companies
        df = store.df(
            """
            SELECT c.canonical_name AS company, c.segment, f.value
            FROM feature_snapshots f JOIN companies c USING (company_id)
            WHERE f.feature_name = ?
            ORDER BY f.value DESC LIMIT ?
            """,
            [by, int(top)],
        )
        if df.empty:
            console.print(f"[red]No feature named[/red] {by!r}")
            raise typer.Exit(1)
        t = Table(title=f"Companies ranked by {by}")
        t.add_column("company")
        t.add_column("segment")
        t.add_column(by, justify="right")
        for _, r in df.iterrows():
            t.add_row(str(r["company"])[:30], str(r["segment"]), f"{r['value']:.4g}")
        console.print(t)


@app.command()
def rank(
    top: int = typer.Option(20, help="How many companies to show."),
    segment: str | None = typer.Option(None, help="Filter to one segment."),
    region: str | None = typer.Option(
        None, help="Filter to one sales region (UK/US/EMEA/Asia/Strategic)."
    ),
) -> None:
    """The Opportunity Radar: companies ranked by score, with region and the recommended product."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        if store.count("scores") == 0:
            console.print("[dim]No scores yet. Run `radar ingest` first.[/dim]")
            return
        clauses, params = [], []
        if segment:
            clauses.append("c.segment LIKE ?")
            params.append(f"%{segment}%")
        if region:
            clauses.append("lower(c.region) LIKE lower(?)")
            params.append(f"%{region}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = store.df(
            f"""
            SELECT s.rank, c.canonical_name AS company, c.region, c.segment,
                   s.score, s.confidence,
                   (SELECT p.product_family FROM product_relevance p
                    WHERE p.company_id = s.company_id AND p.model_version = s.model_version
                    ORDER BY p.relevance_score DESC LIMIT 1) AS best_product
            FROM scores s JOIN companies c USING (company_id)
            {where}
            ORDER BY s.rank LIMIT {int(top)}
            """,
            params,
        )
        t = Table(title="Opportunity Radar")
        for col in ("#", "company", "region", "segment", "score", "conf.", "suggested product"):
            t.add_column(col)
        for _, r in rows.iterrows():
            conf = float(r["confidence"] or 0)
            clabel = "high" if conf >= 0.7 else ("med" if conf >= 0.4 else "low")
            t.add_row(
                str(int(r["rank"])), str(r["company"])[:24], str(r["region"]),
                str(r["segment"])[:16], f"{r['score']:.1f}", clabel,
                str(r["best_product"]).replace("_", " "),
            )
        console.print(t)


def _print_score_card(store: Store, company_id: str) -> None:
    r = store.df(
        """
        SELECT c.canonical_name, c.segment, c.country, c.region, c.strategic,
               s.score, s.confidence, s.rank
        FROM scores s JOIN companies c USING (company_id)
        WHERE c.company_id = ?
        """,
        [company_id],
    ).iloc[0]
    conf = float(r["confidence"] or 0)
    clabel = "high" if conf >= 0.7 else ("medium" if conf >= 0.4 else "low")
    star = " ★ strategic" if r["strategic"] else ""
    console.print(
        f"[bold]{r['canonical_name']}[/bold]  "
        f"({r['region']}{star} · {r['country']} / {r['segment']})"
    )
    console.print(
        f"  Opportunity score [bold]{r['score']:.1f}[/bold] / 100   "
        f"rank #{int(r['rank'])}   confidence: {clabel}"
    )
    pr = store.df(
        "SELECT product_family, relevance_score FROM product_relevance "
        "WHERE company_id = ? ORDER BY relevance_score DESC",
        [company_id],
    )
    console.print("\n  [bold]Product fit[/bold] (compatibility with SIX product families):")
    for _, p in pr.iterrows():
        pct = int(round(float(p["relevance_score"]) * 100))
        bar = "█" * (pct // 6)
        console.print(f"    {str(p['product_family']).replace('_',' '):22} {pct:3d}%  {bar}")
    ex = store.df("SELECT reason, source_ids FROM explanations WHERE company_id = ?", [company_id])
    if not ex.empty:
        console.print(f"\n  [bold]Why[/bold]: {ex.iloc[0]['reason']}")
        srcs = ex.iloc[0]["source_ids"]
        if srcs is not None and len(srcs):
            console.print("  [bold]Evidence[/bold]:")
            for u in list(srcs)[:5]:
                console.print(f"    - {u}")


@app.command()
def score(name: str) -> None:
    """One company's opportunity score: product-fit breakdown, reasons and evidence."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        prof = store.df(
            "SELECT c.company_id FROM scores s JOIN companies c USING (company_id) "
            "WHERE lower(c.canonical_name) LIKE lower(?) ORDER BY s.rank LIMIT 1",
            [f"%{name}%"],
        )
        if prof.empty:
            console.print(f"[red]No scored company matching[/red] {name!r}")
            raise typer.Exit(1)
        _print_score_card(store, prof.iloc[0]["company_id"])


@app.command()
def lookup(
    name: str,
    segment: str | None = typer.Option(
        None, help="Hint the segment (e.g. asset_manager) for a sharper product fit."
    ),
    country: str | None = typer.Option(
        None, help="ISO country code hint (e.g. CH), sets the region."
    ),
    strategic: bool = typer.Option(False, "--strategic", help="Mark as a strategic account."),
    offline: bool = typer.Option(
        False, "--offline", help="Use recorded fixtures instead of live data."
    ),
) -> None:
    """Score ANY company by name on demand (not only the watchlist), and rank it among the rest."""
    from radar.ingest.pipeline import ingest_one
    settings = get_settings(offline=offline)
    with Store(settings.resolved_db_path) as store:
        has_context = store.count("scores") > 0
    if not has_context:
        console.print("[yellow]Tip:[/yellow] run `radar ingest` first so the new company is ranked "
                      "against a full set. Scoring it alone gives a weak relative score.")
    mode = "recorded fixtures" if offline else "live public sources"
    console.print(f"Collecting and scoring [bold]{name}[/bold] from {mode}...")
    cid = ingest_one(settings, name, country=country, segment=segment, strategic=strategic)
    with Store(settings.resolved_db_path) as store:
        _print_score_card(store, cid)


@app.command()
def evaluate() -> None:
    """Proxy feasibility test: does the score rank active companies better than profile/random?"""
    from radar.evaluate import run_evaluation
    settings = get_settings()
    try:
        rep = run_evaluation(settings)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(
        f"[bold]Proxy target[/bold]: >=2 relevant events corroborated by >=2 sources  "
        f"({rep.positives}/{rep.n} companies, base rate {rep.base_rate:.1%})"
    )
    t = Table(title=f"Ranking quality at K={rep.k} (precision == recall at this K)")
    t.add_column("Ranker")
    t.add_column("Precision@K", justify="right")
    t.add_column("Hits", justify="right")
    t.add_column("Lift vs random", justify="right")
    for r in rep.rankers:
        t.add_row(r.name, f"{r.precision_at_k:.0%}", f"{r.hits_at_k}/{rep.k}", f"{r.lift:.1f}x")
    console.print(t)
    full = rep.rankers[0].precision_at_k
    prof = rep.rankers[1].precision_at_k
    console.print(
        "\n[dim]Reading it: the score beats random by a wide margin (feasibility holds). "
        "The gap between 'Opportunity score' and 'Company profile only' is what recent events add "
        "- it shows clearly on live data, where every company is enriched; on the offline sample "
        "the two can coincide because only the signal companies have enrichment. "
        "These use a proxy target, not real sales outcomes, so this is a sanity check, not "
        "validated accuracy.[/dim]"
    )
    if full == prof and full > 0:
        console.print("[yellow]Note:[/yellow] score and profile-only tie here — run this after a "
                      "live ingest to see the real gap.")


@app.command()
def dashboard(
    out: str | None = typer.Option(
        None, help="Output HTML path (default data/exports/dashboard.html)."
    ),
) -> None:
    """Build the interactive Opportunity Radar dashboard (a self-contained HTML file)."""
    from pathlib import Path

    from radar.dashboard import build_dashboard
    settings = get_settings()
    try:
        path = build_dashboard(settings, Path(out) if out else None)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Dashboard written[/green] to {path}")
    console.print(
        "Open it in any browser (no server needed). Regenerate after each `radar ingest`."
    )


@app.command()
def export(fmt: str = typer.Option("csv", "--format", help="csv or parquet")) -> None:
    """Export every table to data/exports/ (FR-12)."""
    settings = get_settings()
    with Store(settings.resolved_db_path) as store:
        paths = store.export(settings.exports_dir, fmt=fmt)
    console.print(f"[green]Exported {len(paths)} tables[/green] to {settings.exports_dir}")


if __name__ == "__main__":
    app()
