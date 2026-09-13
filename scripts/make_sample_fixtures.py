"""Generate SYNTHETIC sample fixtures for offline mode and tests.

These are NOT real scraped data. They are small, realistic, hand-built responses that let
`radar ingest --offline` and the test-suite run deterministically with no internet. Live mode
(`radar ingest --live`) collects the real public data from Wikidata, Wikipedia, Google News RSS
and GDELT. Regenerate with:  python scripts/make_sample_fixtures.py
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures"
RETRIEVED = "2026-09-01T09:00:00+00:00"


def slugify(text: str) -> str:
    keep = ["".join(c.lower() if c.isalnum() else "-" for c in text)][0]
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep.strip("-")[:80] or "x"


def write(connector: str, key: str, url: str, body: str, params: dict | None = None) -> None:
    path = FIX / connector / f"{slugify(key)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"url": url, "params": params or {}, "status_code": 200,
             "retrieved_at": RETRIEVED, "body": body},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def d(days_ago: int) -> str:
    return (date(2026, 9, 1) - timedelta(days=days_ago)).strftime("%a, %d %b %Y 08:00:00 GMT")


def gdelt_date(days_ago: int) -> str:
    return (date(2026, 9, 1) - timedelta(days=days_ago)).strftime("%Y%m%dT120000Z")


# company -> (wikidata qid, employees, listed, domain, wiki summary, [ (title, days_ago, publisher) ])
COMPANIES = {
    "Partners Group Holding AG": (
        "Q680473", 1800, True, "partnersgroup.com",
        "Partners Group Holding AG is a Swiss-based global private markets investment manager, "
        "managing assets across private equity, private credit, infrastructure and real estate.",
        [
            ("Partners Group acquires US-based infrastructure services platform for $1.2bn", 12, "Reuters"),
            ("Partners Group launches new evergreen private markets fund for wealth clients", 30, "Bloomberg"),
            ("Partners Group expands into Japan with new Tokyo office", 55, "Financial Times"),
            ("Partners Group appoints new co-CEO to lead next growth phase", 70, "Finews"),
            ("Partners Group partners with regional bank on private credit distribution", 90, "Citywire"),
        ],
    ),
    "Julius Baer Group Ltd": (
        "Q564132", 7000, True, "juliusbaer.com",
        "Julius Baer Group Ltd is a Swiss multinational private banking and wealth management "
        "company headquartered in Zurich.",
        [
            ("Julius Baer expands wealth management presence in the Middle East", 20, "Reuters"),
            ("Julius Baer launches digital advisory platform for next-generation clients", 40, "Finews"),
            ("Julius Baer faces regulatory review over lending practices", 60, "Bloomberg"),
        ],
    ),
    "Amundi SA": (
        "Q2861111", 5400, True, "amundi.com",
        "Amundi is a French asset management company, the largest asset manager in Europe by "
        "assets under management.",
        [
            ("Amundi launches new range of active ETFs across European markets", 8, "Financial Times"),
            ("Amundi acquires majority stake in Asian fintech distribution platform", 25, "Reuters"),
            ("Amundi expands ESG data capabilities with new partnership", 48, "Citywire"),
            ("Amundi reports record assets under management in full-year results", 80, "Bloomberg"),
        ],
    ),
    "Schroders plc": (
        "Q2000954", 6000, True, "schroders.com",
        "Schroders plc is a British multinational asset management company headquartered in London.",
        [
            ("Schroders launches private markets fund targeting infrastructure debt", 15, "Financial Times"),
            ("Schroders partners with wealth platform to broaden retail distribution", 45, "Citywire"),
            ("Schroders hires senior team to build out private assets business", 65, "Reuters"),
        ],
    ),
    "BlackRock Inc": (
        "Q219635", 19800, True, "blackrock.com",
        "BlackRock, Inc. is an American multinational investment management corporation, the "
        "world's largest asset manager by assets under management.",
        [
            ("BlackRock acquires private markets data provider to expand Aladdin", 10, "Bloomberg"),
            ("BlackRock launches tokenized money market fund on public blockchain", 28, "Reuters"),
            ("BlackRock expands active ETF lineup in Europe", 52, "Financial Times"),
        ],
    ),
    "Euronext NV": (
        "Q1345680", 2200, True, "euronext.com",
        "Euronext N.V. is a pan-European bourse operating regulated markets in several countries, "
        "and a provider of market data and post-trade services.",
        [
            ("Euronext acquires Nordic clearing business to expand post-trade", 18, "Reuters"),
            ("Euronext launches new suite of ESG indices and data products", 35, "Bloomberg"),
            ("Euronext expands data services division with analytics acquisition", 75, "Financial Times"),
        ],
    ),
}


def build_rss(company: str, items: list[tuple[str, int, str]]) -> str:
    entries = []
    for title, days_ago, pub in items:
        link = f"https://news.example/{slugify(title)}"
        entries.append(
            f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid>{link}</guid>
      <pubDate>{d(days_ago)}</pubDate>
      <source url="https://{slugify(pub)}.example">{pub}</source>
      <description>{title}. [synthetic sample fixture]</description>
    </item>"""
        )
    body = "\n".join(entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>{company} - synthetic sample feed</title>
{body}
</channel></rss>"""


def build_gdelt(company: str, items: list[tuple[str, int, str]]) -> str:
    arts = []
    for title, days_ago, pub in items[:3]:
        arts.append({
            "url": f"https://{slugify(pub)}.example/{slugify(title)}",
            "title": title,
            "seendate": gdelt_date(days_ago + 1),
            "domain": f"{slugify(pub)}.example",
            "language": "English",
        })
    return json.dumps({"articles": arts})


def build_wikidata_search(qid: str) -> str:
    return json.dumps({"search": [{"id": qid}]})


def build_wikidata_entity(qid: str, employees: int, listed: bool, domain: str) -> str:
    claims: dict = {
        "P1128": [{"mainsnak": {"datavalue": {"value": {"amount": f"+{employees}"}}}}],
        "P856": [{"mainsnak": {"datavalue": {"value": f"https://{domain}"}}}],
        "P17": [{"mainsnak": {"datavalue": {"value": {"id": "Q39"}}}}],
        "P452": [{"mainsnak": {"datavalue": {"value": {"id": "Q806718"}}}}],
    }
    if listed:
        claims["P414"] = [{"mainsnak": {"datavalue": {"value": {"id": "Q1332144"}}}}]
    return json.dumps({"entities": {qid: {"claims": claims, "labels": {"en": {"value": qid}}}}})


def build_wikipedia(company: str, summary: str) -> str:
    return json.dumps({
        "extract": summary,
        "content_urls": {"desktop": {"page": f"https://en.wikipedia.org/wiki/{company.replace(' ', '_')}"}},
    })


def unix_days_ago(days_ago: int) -> int:
    # seconds since epoch for 12:00 on the dated day
    from datetime import datetime, timezone
    dt = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc) - timedelta(days=days_ago)
    return int(dt.timestamp())


def build_yahoo(items: list[tuple[str, int, str]]) -> str:
    # Yahoo reports the SAME headlines as Google News/GDELT -> exercises cross-source dedup.
    news = [
        {
            "title": title,
            "link": f"https://finance.yahoo.example/news/{slugify(title)}",
            "publisher": pub,
            "providerPublishTime": unix_days_ago(days_ago),
        }
        for title, days_ago, pub in items[:3]
    ]
    return json.dumps({"news": news})


def build_edgar(company: str, items: list[tuple[str, int, str]]) -> str:
    # An 8-K current report corresponding to the first (acquisition) story, plus an annual report.
    # These get their own distinct insights (a filing has a generic title, not the news headline).
    _title, days_ago, _pub = items[0]
    hits = [
        {
            "_id": f"0000000000-26-{100000 + i}:doc.htm",
            "_source": {
                "display_names": [f"{company} (CIK 0000000000)"],
                "file_date": (date(2026, 9, 1) - timedelta(days=day)).isoformat(),
                "root_form": form,
                "url": f"https://www.sec.gov/Archives/edgar/data/0/{slugify(company)}-{form}.htm",
            },
        }
        for i, (form, day) in enumerate([("8-K", days_ago), ("10-K", 100)])
    ]
    return json.dumps({"hits": {"hits": hits}})


def main() -> None:
    for company, (qid, emp, listed, domain, summary, items) in COMPANIES.items():
        write("wikidata", f"search-{company}",
              "https://www.wikidata.org/w/api.php", build_wikidata_search(qid))
        write("wikidata", f"entity-{qid}",
              f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
              build_wikidata_entity(qid, emp, listed, domain))
        write("wikipedia", f"summary-{company}",
              f"https://en.wikipedia.org/api/rest_v1/page/summary/{company.replace(' ', '_')}",
              build_wikipedia(company, summary))
        write("google_news_rss", f"news-{company}",
              "https://news.google.com/rss/search", build_rss(company, items))
        write("gdelt", f"gdelt-{company}",
              "https://api.gdeltproject.org/api/v2/doc/doc", build_gdelt(company, items))
        write("yahoo_finance", f"yahoo-{company}",
              "https://query2.finance.yahoo.com/v1/finance/search", build_yahoo(items))
        write("sec_edgar", f"edgar-{company}",
              "https://efts.sec.gov/LATEST/search-index", build_edgar(company, items))
    total = sum(1 for _ in FIX.rglob("*.json"))
    print(f"wrote {total} fixture files under {FIX}")


if __name__ == "__main__":
    main()
