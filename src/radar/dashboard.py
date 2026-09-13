"""S4 - the Opportunity Radar dashboard.

Renders a single self-contained, interactive HTML app from the scored database: an overview,
the ranked radar with filter / search / sort, and a per-company detail view (score, product-fit
breakdown, explanation, evidence, insight timeline). No server and no external runtime is needed
- the file opens in any browser, which makes it easy to hand to management for the demo (FR-12,
NFR-08). It is a snapshot of the current run; regenerate after each ``radar ingest``.

Design note: we deliberately ship a bespoke dashboard rather than a default Streamlit app, whose
stock look is exactly the generic style to avoid. All interactivity is vanilla JS over an embedded
data blob, so there is nothing to install to view it.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from radar.config import Settings
from radar.models import ProductFamily as PF
from radar.products import PRODUCT_LABEL
from radar.scoring import MODEL_VERSION
from radar.storage import Store

CONN_LABEL = {
    "google_news_rss": "Google News", "gdelt": "GDELT",
    "yahoo_finance": "Yahoo Finance", "sec_edgar": "SEC EDGAR",
}
# product family -> (light hue, dark hue), fixed categorical order (validated palette)
FAMILY_HUE = {
    PF.REFERENCE_DATA: ("#2a78d6", "#3987e5"),
    PF.MARKET_DATA: ("#eb6834", "#e0703f"),
    PF.FUNDS_DATA: ("#1baf7a", "#22c58a"),
    PF.CORPORATE_ACTIONS: ("#c98500", "#e0a020"),
    PF.REGULATORY_TAX: ("#c95b86", "#d981a6"),
    PF.ESG: ("#2f8f3e", "#43a84f"),
}


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def collect_data(store: Store) -> dict:
    companies = store.df(
        """
        SELECT c.company_id, c.canonical_name, c.country, c.segment, c.size_band, c.listed,
               c.region, c.strategic, c.description, c.enrichment_confidence,
               s.score, s.rank, s.confidence
        FROM companies c JOIN scores s USING (company_id)
        WHERE s.model_version = ?
        ORDER BY s.rank
        """,
        [MODEL_VERSION],
    )
    prod = store.df(
        "SELECT company_id, product_family, relevance_score FROM product_relevance "
        "WHERE model_version = ?",
        [MODEL_VERSION],
    )
    expl = store.df(
        "SELECT company_id, reason, source_ids FROM explanations WHERE model_version = ?",
        [MODEL_VERSION],
    )
    ins = store.df(
        """
        SELECT i.company_id, i.canonical_title, i.insight_type, i.event_date,
               i.source_count, i.connectors
        FROM insights i ORDER BY i.event_date DESC NULLS LAST
        """
    )

    prod_by = {}
    for r in prod.itertuples():
        prod_by.setdefault(r.company_id, []).append((PF(r.product_family), float(r.relevance_score)))
    expl_by = {r.company_id: (r.reason, list(r.source_ids) if r.source_ids is not None else [])
               for r in expl.itertuples()}
    ins_by = {}
    for r in ins.itertuples():
        ins_by.setdefault(r.company_id, []).append({
            "title": r.canonical_title, "type": r.insight_type,
            "date": str(r.event_date)[:10] if r.event_date is not None else None,
            "sources": int(r.source_count),
            "connectors": list(r.connectors) if r.connectors is not None else [],
        })

    rows = []
    for c in companies.itertuples():
        cid = c.company_id
        products = sorted(prod_by.get(cid, []), key=lambda x: -x[1])
        best = products[0] if products else (PF.REFERENCE_DATA, 0.0)
        reason, evidence = expl_by.get(cid, ("", []))
        signals = ins_by.get(cid, [])
        rows.append({
            "id": cid, "name": c.canonical_name, "country": c.country or "",
            "region": c.region or "EMEA",
            "strategic": (False if pd.isna(c.strategic) else bool(c.strategic)),
            "segment": c.segment or "", "size_band": c.size_band or "unknown",
            "listed": (None if pd.isna(c.listed) else bool(c.listed)),
            "description": (c.description or ""),
            "score": round(float(c.score), 1), "rank": int(c.rank),
            "confidence": round(float(c.confidence or 0), 3),
            "best_product": best[0].value, "best_product_label": PRODUCT_LABEL[best[0]],
            "products": [{"fam": f.value, "label": PRODUCT_LABEL[f],
                          "pct": int(round(v * 100))} for f, v in products],
            "reason": reason, "evidence": evidence, "signals": signals,
            "n_signals": len(signals),
        })

    counts = store.counts()
    with_signals = sum(1 for r in rows if r["n_signals"] > 0)
    top_avg = round(sum(r["score"] for r in rows[:with_signals or 1]) / (with_signals or 1), 1)
    # score distribution (10 buckets)
    dist = [0] * 10
    for r in rows:
        b = min(int(r["score"] // 10), 9)
        dist[b] += 1
    # insights by source
    isrc = store.df("SELECT connector, count(*) n FROM insight_sources GROUP BY 1")
    by_source = {r.connector: int(r.n) for r in isrc.itertuples()}
    # product mix among the companies that have signals
    mix: dict[str, int] = {}
    for r in rows[:max(with_signals, 10)]:
        mix[r["best_product_label"]] = mix.get(r["best_product_label"], 0) + 1
    # per-region: count and how many are flagged (have signals), in the team's region order
    region_order = ["UK", "US", "EMEA", "Asia", "Strategic Accounts"]
    by_region = {}
    for reg in region_order:
        members = [r for r in rows if r["region"] == reg]
        if members:
            by_region[reg] = {"n": len(members),
                              "flagged": sum(1 for r in members if r["n_signals"] > 0)}

    return {
        "meta": {"generated": datetime.now().strftime("%d %b %Y %H:%M"),
                 "model": MODEL_VERSION},
        "summary": {
            "companies": counts["companies"], "with_signals": with_signals,
            "insights": counts["insights"],
            "new_insights": store.df("SELECT count(*) n FROM insights WHERE is_new").iloc[0]["n"],
            "top_avg": top_avg, "events": counts["events"],
        },
        "dist": dist, "by_source": by_source, "mix": mix, "by_region": by_region,
        "regions": [r for r in region_order if r in by_region],
        "segments": sorted({r["segment"] for r in rows if r["segment"]}),
        "countries": sorted({r["country"] for r in rows if r["country"]}),
        "companies": rows,
    }


def build_dashboard(settings: Settings, out_path: Path | None = None) -> Path:
    out_path = out_path or (settings.exports_dir / "dashboard.html")
    with Store(settings.resolved_db_path) as store:
        if store.count("scores") == 0:
            raise RuntimeError("No scores in the database. Run `radar ingest` first.")
        data = collect_data(store)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render(data), encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------------------------

def _family_vars() -> tuple[str, str]:
    light = "\n".join(f"  --pf-{f.value.replace('_','-')}: {lt};" for f, (lt, dk) in FAMILY_HUE.items())
    dark = "\n".join(f"    --pf-{f.value.replace('_','-')}: {dk};" for f, (lt, dk) in FAMILY_HUE.items())
    return light, dark


def _conf_label(c: float) -> str:
    return "high" if c >= 0.7 else ("medium" if c >= 0.4 else "low")


def _row_html(r: dict) -> str:
    conf = _conf_label(r["confidence"])
    sig = 1 if r["n_signals"] > 0 else 0
    pfv = r["best_product"].replace("_", "-")
    return (
        f'<tr class="row" data-id="{_esc(r["id"])}" data-score="{r["score"]}" '
        f'data-rank="{r["rank"]}" data-name="{_esc(r["name"].lower())}" '
        f'data-segment="{_esc(r["segment"])}" data-country="{_esc(r["country"])}" '
        f'data-region="{_esc(r["region"])}" data-signals="{sig}" tabindex="0">'
        f'<td class="c-rank">{r["rank"]}</td>'
        f'<td class="c-co"><span class="co-name">{_esc(r["name"])}'
        f'{" ★" if r.get("strategic") else ""}</span>'
        f'<span class="co-seg">{_esc(r["segment"].replace("_"," "))}</span></td>'
        f'<td class="c-region">{_esc(r["region"])}</td>'
        f'<td class="c-score"><span class="score-bar"><span class="score-fill" '
        f'style="width:{r["score"]}%"></span></span><span class="score-num">{r["score"]:.1f}</span></td>'
        f'<td class="c-conf"><span class="conf conf-{conf}">{conf}</span></td>'
        f'<td class="c-prod"><span class="pf-dot" style="background:var(--pf-{pfv})"></span>'
        f'{_esc(r["best_product_label"])}</td>'
        f'</tr>'
    )


def _bars_svg(pairs: list[tuple[str, int]], color_fn, width=270, rh=26) -> str:
    if not pairs:
        return ""
    mx = max(v for _, v in pairs) or 1
    h = len(pairs) * rh + 8
    lblw = 108
    barmax = width - lblw - 34
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img">']
    for i, (label, v) in enumerate(pairs):
        y = i * rh + 6
        bw = max(2, round(barmax * v / mx))
        col = color_fn(label)
        out.append(
            f'<text x="0" y="{y+13}" class="bl">{_esc(label)}</text>'
            f'<rect x="{lblw}" y="{y+3}" width="{bw}" height="15" rx="3" fill="{col}"><title>{_esc(label)}: {v}</title></rect>'
            f'<text x="{lblw+bw+6}" y="{y+13}" class="bv">{v}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _dist_svg(dist: list[int], width=340, height=120) -> str:
    mx = max(dist) or 1
    n = len(dist)
    gap = 5
    bw = (width - (n - 1) * gap - 10) / n
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">']
    for i, v in enumerate(dist):
        x = 5 + i * (bw + gap)
        bh = round((height - 26) * v / mx)
        y = height - 20 - bh
        out.append(
            f'<rect x="{x:.1f}" y="{y}" width="{bw:.1f}" height="{bh}" rx="3" '
            f'fill="var(--accent)" opacity="{0.45 + 0.55*i/n:.2f}"><title>{i*10}-{i*10+10}: {v}</title></rect>'
            f'<text x="{x+bw/2:.1f}" y="{height-6}" class="xt">{i*10}</text>'
        )
    out.append("</svg>")
    return "".join(out)


def _render(data: dict) -> str:
    s = data["summary"]
    rows_html = "\n".join(_row_html(r) for r in data["companies"])
    light_pf, dark_pf = _family_vars()

    def fam_color(label):
        for f, _ in FAMILY_HUE.items():
            if PRODUCT_LABEL[f] == label:
                return f"var(--pf-{f.value.replace('_','-')})"
        return "var(--accent)"

    mix_svg = _bars_svg(sorted(data["mix"].items(), key=lambda x: -x[1]), fam_color)
    src_pairs = [(CONN_LABEL.get(k, k), v) for k, v in
                 sorted(data["by_source"].items(), key=lambda x: -x[1])]
    src_svg = _bars_svg(src_pairs, lambda _l: "var(--accent)")
    dist_svg = _dist_svg(data["dist"])
    region_pairs = [(reg, d["n"]) for reg, d in data["by_region"].items()]
    region_svg = _bars_svg(region_pairs, lambda _l: "var(--accent)")

    seg_opts = "".join(f'<option value="{_esc(x)}">{_esc(x.replace("_"," "))}</option>'
                       for x in data["segments"])
    reg_opts = "".join(f'<option value="{_esc(x)}">{_esc(x)}</option>' for x in data["regions"])
    blob = json.dumps({"companies": data["companies"]}, ensure_ascii=False)

    return f"""<title>Opportunity Radar</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
{_CSS.replace("__LIGHT_PF__", light_pf).replace("__DARK_PF__", dark_pf)}
</style>

<header class="top">
  <div class="brand">
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <circle cx="13" cy="13" r="11.5" fill="none" stroke="var(--border)" stroke-width="1.5"/>
      <circle cx="13" cy="13" r="7" fill="none" stroke="var(--border)" stroke-width="1.5"/>
      <circle cx="13" cy="13" r="1.8" fill="var(--accent)"/>
      <path d="M13 13 L13 1.5 A11.5 11.5 0 0 1 23.4 8.2 Z" fill="var(--accent)" opacity=".22"/>
      <line x1="13" y1="13" x2="13" y2="1.5" stroke="var(--accent)" stroke-width="1.5"/>
    </svg>
    <span class="name">Opportunity Radar</span>
  </div>
  <span class="flex"></span>
  <span class="run">{_esc(s['companies'])} companies · model {_esc(data['meta']['model'])} · {_esc(data['meta']['generated'])}</span>
  <button class="tgl" id="tgl" type="button">◐</button>
</header>

<div class="note"><b>Sample run.</b> Rendered from an offline run on synthetic fixture data. Scores are relevance/propensity proxies, not conversion probabilities. Live mode collects real public data.</div>

<section class="kpis">
  <div class="kpi"><div class="k">{s['companies']}</div><div class="l">Companies tracked</div></div>
  <div class="kpi"><div class="k">{s['with_signals']}</div><div class="l">With live signals</div></div>
  <div class="kpi hl"><div class="k">{s['top_avg']:.0f}</div><div class="l">Avg score, flagged</div></div>
  <div class="kpi"><div class="k">{s['insights']}</div><div class="l">Distinct insights</div></div>
  <div class="kpi"><div class="k">{s['events']}&rarr;{s['insights']}</div><div class="l">Reports deduplicated</div></div>
</section>

<section class="charts">
  <div class="chart"><h3>Companies by region</h3>{region_svg}</div>
  <div class="chart"><h3>Score distribution</h3>{dist_svg}</div>
  <div class="chart"><h3>Insights by source</h3>{src_svg}</div>
  <div class="chart"><h3>Suggested product mix</h3>{mix_svg}</div>
</section>

<div class="main">
  <section class="listwrap">
    <div class="controls">
      <label class="search"><svg width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="5" stroke="currentColor" stroke-width="1.6"/><line x1="11" y1="11" x2="14.5" y2="14.5" stroke="currentColor" stroke-width="1.6"/></svg><input id="q" placeholder="Search company or segment…" autocomplete="off"></label>
      <select id="freg"><option value="">All regions</option>{reg_opts}</select>
      <select id="fseg"><option value="">All segments</option>{seg_opts}</select>
      <button class="chip" id="fsig" type="button">Signals only</button>
      <label class="slider">min score <input type="range" id="fscore" min="0" max="90" value="0" step="5"><span id="fscorev">0</span></label>
    </div>
    <div class="showing" id="showing"></div>
    <div class="tablescroll">
      <table class="radar">
        <thead><tr>
          <th data-sort="rank" class="th-rank">#</th>
          <th data-sort="name">Company</th>
          <th data-sort="region">Region</th>
          <th data-sort="score" class="th-active">Score ▾</th>
          <th data-sort="conf">Conf.</th>
          <th data-sort="product">Suggested product</th>
        </tr></thead>
        <tbody id="tbody">
{rows_html}
        </tbody>
      </table>
    </div>
  </section>

  <aside class="detail" id="detail"><!-- filled by JS on load --></aside>
</div>

<footer class="foot">Opportunity Radar · external public-data POC · a salesperson decides; the tool only prioritizes.</footer>

<script id="data" type="application/json">{blob}</script>
<script>
{_JS}
</script>"""


_CSS = r"""
:root{
  --ground:#eef1f5; --surface:#ffffff; --surface-2:#f5f8fb;
  --ink:#0f1b2d; --ink-2:#54606f; --muted:#8b97a8; --border:#e2e8f0; --border-2:#eef2f7;
  --accent:#0f766e; --accent-ink:#0b5f58; --accent-soft:rgba(15,118,110,.10);
  --good:#2f8f3e; --warn:#b7791f; --shadow:0 1px 2px rgba(15,27,45,.06),0 10px 30px rgba(15,27,45,.06);
__LIGHT_PF__
  --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  --body:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  --disp:"Archivo","IBM Plex Sans",system-ui,sans-serif;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0a1120; --surface:#101b2c; --surface-2:#0d1725;
  --ink:#e7eef7; --ink-2:#9db0c7; --muted:#6b7a92; --border:#1e2c40; --border-2:#182437;
  --accent:#2dd4bf; --accent-ink:#5eead4; --accent-soft:rgba(45,212,191,.12);
  --good:#4ade80; --warn:#fbbf24; --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 34px rgba(0,0,0,.4);
__DARK_PF__
}}
:root[data-theme="dark"]{
  --ground:#0a1120; --surface:#101b2c; --surface-2:#0d1725;
  --ink:#e7eef7; --ink-2:#9db0c7; --muted:#6b7a92; --border:#1e2c40; --border-2:#182437;
  --accent:#2dd4bf; --accent-ink:#5eead4; --accent-soft:rgba(45,212,191,.12);
  --good:#4ade80; --warn:#fbbf24; --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 34px rgba(0,0,0,.4);
__DARK_PF__
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);font-family:var(--body);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;padding:0 20px 40px}
h1,h2,h3{margin:0;font-family:var(--disp);letter-spacing:-.01em}
.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;padding:13px 0;margin:0 -20px 0;padding-inline:20px;background:color-mix(in srgb,var(--ground) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:10px}
.brand .name{font-family:var(--disp);font-weight:800;font-size:18px;letter-spacing:-.02em}
.flex{flex:1}
.run{font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.tgl{font-family:var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--ink-2);padding:5px 10px;cursor:pointer}
.tgl:hover{border-color:var(--accent)}
.note{background:var(--accent-soft);border:1px solid color-mix(in srgb,var(--accent) 24%,transparent);color:var(--accent-ink);border-radius:10px;padding:9px 13px;font-size:12.5px;margin-top:16px}
.note b{font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-top:14px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 15px}
.kpi .k{font-family:var(--disp);font-weight:700;font-size:26px;line-height:1;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .l{font-size:11.5px;color:var(--ink-2);margin-top:7px}
.kpi.hl .k{color:var(--accent)}
.charts{display:grid;grid-template-columns:repeat(3,1fr);gap:11px;margin-top:11px}
.chart{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:13px 15px}
.chart h3{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:8px}
.bl{fill:var(--ink-2);font:500 11px var(--body)}
.bv{fill:var(--ink);font:600 11px var(--mono)}
.xt{fill:var(--muted);font:500 9px var(--mono);text-anchor:middle}
.main{display:grid;grid-template-columns:1fr 372px;gap:16px;margin-top:16px;align-items:start}
.listwrap{background:var(--surface);border:1px solid var(--border);border-radius:13px;overflow:hidden}
.controls{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:13px 14px;border-bottom:1px solid var(--border-2)}
.search{flex:1;min-width:170px;display:flex;align-items:center;gap:7px;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:7px 10px;color:var(--muted)}
.search input{border:0;background:transparent;color:var(--ink);font:inherit;width:100%;outline:none}
select,.slider{font-family:var(--mono);font-size:12px;color:var(--ink-2);background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:7px 9px}
.slider{display:flex;align-items:center;gap:7px}
.slider input{accent-color:var(--accent)}
.chip{font-family:var(--mono);font-size:12px;color:var(--ink-2);background:var(--surface-2);border:1px solid var(--border);border-radius:999px;padding:7px 12px;cursor:pointer}
.chip[aria-pressed="true"]{background:var(--accent);color:#fff;border-color:var(--accent)}
:root[data-theme="dark"] .chip[aria-pressed="true"],:root:not([data-theme="light"]) .chip[aria-pressed="true"]{color:#04211d}
.showing{font-family:var(--mono);font-size:11.5px;color:var(--muted);padding:9px 14px 0}
.tablescroll{max-height:66vh;overflow:auto}
table.radar{width:100%;border-collapse:collapse;font-size:13px}
.radar thead th{position:sticky;top:0;background:var(--surface);text-align:left;font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;padding:9px 12px;border-bottom:1px solid var(--border);cursor:pointer;white-space:nowrap}
.radar thead th:hover{color:var(--ink)}
.th-active{color:var(--accent)}
.radar td{padding:9px 12px;border-bottom:1px solid var(--border-2);vertical-align:middle}
.row{cursor:pointer}
.row:hover{background:var(--surface-2)}
.row.sel{background:var(--accent-soft)}
.row.sel td:first-child{box-shadow:inset 3px 0 0 var(--accent)}
.c-rank{font-family:var(--mono);color:var(--muted);font-variant-numeric:tabular-nums;width:34px}
.co-name{display:block;font-weight:600}
.co-seg{display:block;font-family:var(--mono);font-size:10.5px;color:var(--muted);text-transform:capitalize}
.c-region{font-family:var(--mono);color:var(--ink-2);font-size:12px}
.c-score{white-space:nowrap;width:130px}
.score-bar{display:inline-block;width:62px;height:7px;border-radius:999px;background:var(--surface-2);vertical-align:middle;overflow:hidden;margin-right:8px;border:1px solid var(--border-2)}
.score-fill{display:block;height:100%;background:var(--accent);border-radius:999px}
.score-num{font-family:var(--mono);font-weight:600;font-variant-numeric:tabular-nums}
.conf{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:5px;border:1px solid var(--border)}
.conf-high{color:var(--good);border-color:color-mix(in srgb,var(--good) 40%,transparent)}
.conf-medium{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,transparent)}
.conf-low{color:var(--muted)}
.c-prod{white-space:nowrap}
.pf-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
/* detail */
.detail{position:sticky;top:74px;background:var(--surface);border:1px solid var(--border);border-radius:13px;padding:17px 18px;box-shadow:var(--shadow)}
.d-rank{font-family:var(--mono);font-size:11px;color:var(--muted)}
.d-name{font-family:var(--disp);font-weight:700;font-size:20px;margin:3px 0 2px;text-wrap:balance}
.d-meta{font-family:var(--mono);font-size:11.5px;color:var(--muted);text-transform:capitalize}
.d-scorewrap{display:flex;align-items:center;gap:16px;margin:15px 0 6px}
.gauge{--v:0;width:72px;height:72px;border-radius:50%;flex:0 0 auto;background:conic-gradient(var(--accent) calc(var(--v)*1%),var(--surface-2) 0);display:grid;place-items:center}
.gauge::after{content:"";position:absolute;width:54px;height:54px;border-radius:50%;background:var(--surface)}
.gauge b{position:relative;font-family:var(--disp);font-weight:700;font-size:20px;font-variant-numeric:tabular-nums}
.d-scoremeta .big{font-family:var(--disp);font-weight:700;font-size:15px}
.d-scoremeta .sub{font-size:12px;color:var(--ink-2)}
.d-sec{margin-top:16px}
.d-sec h4{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600;margin:0 0 9px}
.pfrow{display:grid;grid-template-columns:118px 1fr 30px;align-items:center;gap:8px;margin-bottom:7px}
.pflabel{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-2)}
.pfbar{height:8px;border-radius:999px;background:var(--surface-2);overflow:hidden}
.pffill{display:block;height:100%;border-radius:999px}
.pfval{font-family:var(--mono);font-size:11.5px;text-align:right;font-variant-numeric:tabular-nums}
.why{font-size:13px;line-height:1.55;color:var(--ink)}
.ev{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.evchip{font-family:var(--mono);font-size:10.5px;color:var(--ink-2);background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:3px 7px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tl{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.tl li{display:grid;grid-template-columns:14px 1fr;gap:9px}
.tl .dot{width:9px;height:9px;border-radius:50%;margin-top:5px;background:var(--accent)}
.tl .ti{font-size:12.5px;line-height:1.4}
.tl .tm{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-top:2px}
.empty{color:var(--muted);font-size:12.5px}
.foot{color:var(--muted);font-family:var(--mono);font-size:11px;text-align:center;margin-top:26px}
@media (max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}.charts{grid-template-columns:1fr}.main{grid-template-columns:1fr}.detail{position:static}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""


_JS = r"""
(function(){
  var DATA = JSON.parse(document.getElementById('data').textContent);
  var byId = {}; DATA.companies.forEach(function(c){ byId[c.id]=c; });
  var root = document.documentElement;
  var PF_LABELS = {};
  // theme toggle
  function sysDark(){ return window.matchMedia && matchMedia('(prefers-color-scheme:dark)').matches; }
  document.getElementById('tgl').addEventListener('click', function(){
    var cur = root.getAttribute('data-theme') || (sysDark()?'dark':'light');
    root.setAttribute('data-theme', cur==='dark'?'light':'dark');
  });
  // detail rendering
  function famVar(fam){ return 'var(--pf-'+fam.replace(/_/g,'-')+')'; }
  function confLabel(c){ return c>=0.7?'high':(c>=0.4?'medium':'low'); }
  function esc(s){ var d=document.createElement('div'); d.textContent=s==null?'':s; return d.innerHTML; }
  function renderDetail(id){
    var c = byId[id]; if(!c) return;
    document.querySelectorAll('.row').forEach(function(r){ r.classList.toggle('sel', r.dataset.id===id); });
    var pf = c.products.map(function(p){
      return '<div class="pfrow"><span class="pflabel"><span class="pf-dot" style="background:'+famVar(p.fam)+'"></span>'+esc(p.label)+'</span>'
        +'<span class="pfbar"><span class="pffill" style="width:'+p.pct+'%;background:'+famVar(p.fam)+'"></span></span>'
        +'<span class="pfval">'+p.pct+'%</span></div>';
    }).join('');
    var ev = (c.evidence||[]).slice(0,5).map(function(u){
      var d = String(u).replace(/^https?:\/\//,'').split('/')[0];
      return '<span class="evchip" title="'+esc(u)+'">'+esc(d)+'</span>';
    }).join('');
    var tl = (c.signals||[]).length ? c.signals.map(function(s){
      var conns = (s.connectors||[]).length + ' src';
      return '<li><span class="dot"></span><div><div class="ti">'+esc(s.title)+'</div>'
        +'<div class="tm">'+esc((s.type||'').replace(/_/g,' '))+' · '+esc(s.date||'')+' · '+conns+'</div></div></li>';
    }).join('') : '<li class="empty">No live signals yet — product fit is from segment alone.</li>';
    var conf = confLabel(c.confidence);
    var listedTxt = c.listed===true?'listed':(c.listed===false?'private':'—');
    document.getElementById('detail').innerHTML =
      '<div class="d-rank">RANK #'+c.rank+'</div>'
      +'<div class="d-name">'+esc(c.name)+'</div>'
      +'<div class="d-meta">'+esc(c.region)+(c.strategic?' ★':'')+' · '+esc(c.country)+' · '+esc((c.segment||'').replace(/_/g,' '))+' · '+esc(c.size_band)+' · '+listedTxt+'</div>'
      +'<div class="d-scorewrap"><div class="gauge" style="--v:'+c.score+';position:relative"><b>'+c.score.toFixed(0)+'</b></div>'
      +'<div class="d-scoremeta"><div class="big">'+c.score.toFixed(1)+' / 100</div>'
      +'<div class="sub">confidence: <b>'+conf+'</b></div>'
      +'<div class="sub">suggested: <b>'+esc(c.best_product_label)+'</b></div></div></div>'
      +'<div class="d-sec"><h4>Product fit — compatibility with SIX products</h4>'+pf+'</div>'
      +'<div class="d-sec"><h4>Why flagged</h4><div class="why">'+esc(c.reason)+'</div>'+(ev?'<div class="ev">'+ev+'</div>':'')+'</div>'
      +'<div class="d-sec"><h4>Signal timeline</h4><ul class="tl">'+tl+'</ul></div>';
  }
  // rows
  var tbody = document.getElementById('tbody');
  var rows = [].slice.call(tbody.querySelectorAll('.row'));
  rows.forEach(function(r){
    r.addEventListener('click', function(){ renderDetail(r.dataset.id); });
    r.addEventListener('keydown', function(e){ if(e.key==='Enter'){ renderDetail(r.dataset.id); } });
  });
  // filters
  var q=document.getElementById('q'), fseg=document.getElementById('fseg'), freg=document.getElementById('freg');
  var fsig=document.getElementById('fsig'), fscore=document.getElementById('fscore'), fscorev=document.getElementById('fscorev');
  var showing=document.getElementById('showing'); var sigOnly=false;
  function apply(){
    var term=(q.value||'').trim().toLowerCase(), seg=fseg.value, reg=freg.value, mn=+fscore.value, shown=0;
    fscorev.textContent=mn;
    rows.forEach(function(r){
      var ok = (!term || r.dataset.name.indexOf(term)>=0 || r.dataset.segment.indexOf(term)>=0)
        && (!seg || r.dataset.segment===seg) && (!reg || r.dataset.region===reg)
        && (!sigOnly || r.dataset.signals==='1') && (+r.dataset.score >= mn);
      r.hidden=!ok; if(ok) shown++;
    });
    showing.textContent='Showing '+shown+' of '+rows.length+' companies';
  }
  [q,fseg,freg,fscore].forEach(function(el){ el.addEventListener('input',apply); });
  fsig.addEventListener('click',function(){ sigOnly=!sigOnly; fsig.setAttribute('aria-pressed',sigOnly); apply(); });
  // sort
  var sortKey='score', sortDir=-1;
  document.querySelectorAll('thead th').forEach(function(th){
    th.addEventListener('click', function(){
      var k=th.dataset.sort; if(!k) return;
      if(k===sortKey){ sortDir*=-1; } else { sortKey=k; sortDir = (k==='name'||k==='segment'||k==='region'||k==='product')?1:-1; }
      document.querySelectorAll('thead th').forEach(function(x){ x.classList.remove('th-active'); x.textContent=x.textContent.replace(/ [▾▴]$/,''); });
      th.classList.add('th-active'); th.textContent=th.textContent.replace(/ [▾▴]$/,'')+(sortDir<0?' ▾':' ▴');
      var val=function(r){
        if(k==='name'||k==='segment'||k==='region') return r.dataset[k]||'';
        if(k==='product') return (byId[r.dataset.id]||{}).best_product_label||'';
        if(k==='conf') return +(byId[r.dataset.id]||{}).confidence||0;
        return +r.dataset[k]||0;
      };
      rows.sort(function(a,b){ var x=val(a),y=val(b); return (x<y?-1:x>y?1:0)*sortDir; });
      rows.forEach(function(r){ tbody.appendChild(r); });
    });
  });
  // boot
  apply();
  if(rows.length) renderDetail(rows[0].dataset.id);
})();
"""
