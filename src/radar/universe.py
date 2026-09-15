"""Universe importer - grow the watchlist from thousands of real companies (GLEIF).

The 121-company seed is a demo, not a research universe. This imports a real, auditable company
list from the **GLEIF Golden Copy** - the free, open, bulk register of every legal entity with an
LEI (which every regulated financial firm has). Download the CSV Golden Copy from gleif.org, then:

    radar import-universe path/to/gleif-golden-copy.csv --per-region 1200

It reads the standard GLEIF LEI-CDF CSV columns (matched defensively so minor format changes don't
break it), keeps ACTIVE / ISSUED entities, maps each entity's country to one of our sales regions,
caps how many per region so the universe stays workable, and MERGES into the existing watchlist
(keeping curated rows and their strategic flags). Imported rows get tier ``cold`` so the tiered
refresh can process them less often than the hot, hand-picked accounts.

Two honest limitations, documented rather than hidden:
* GLEIF has no industry field, so this cannot filter to "financial firms" on its own. Pre-filter
  the file, cap per region, or later cross-reference an industry source (BIC/ISIN mapping, or D&B
  when licensed). The ``segment`` is left blank for imported rows and can be enriched later.
* A pluggable ``Source`` seam is left for a **D&B Direct+** adapter for teams that license it -
  same importer shape, premium data, but its own redistribution license (see docs).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from radar.normalize import normalize_name
from radar.regions import GEO_REGIONS, geo_region

# Candidate header names in the GLEIF Golden Copy CSV (LEI-CDF v3.x), matched case-insensitively
# and by "contains" so slight variations still resolve.
COL_LEI = ("LEI",)
COL_NAME = ("Entity.LegalName", "LegalName")
COL_COUNTRY = ("Entity.LegalAddress.Country", "LegalAddress.Country",
               "Entity.HeadquartersAddress.Country")
COL_ENTITY_STATUS = ("Entity.EntityStatus", "EntityStatus")
COL_REG_STATUS = ("Registration.RegistrationStatus", "RegistrationStatus")

SEED_FIELDS = ["seed_name", "country", "segment", "homepage", "notes", "strategic", "tier",
               "seed_source"]


@dataclass
class ImportReport:
    read: int = 0
    kept: int = 0
    skipped_inactive: int = 0
    skipped_region: int = 0
    skipped_dupe: int = 0
    added: int = 0
    per_region: dict[str, int] = field(default_factory=dict)


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    low = {h.lower(): h for h in headers}
    for c in candidates:
        if c.lower() in low:
            return low[c.lower()]
    for h in headers:  # fall back to a "contains" match on the last path segment
        for c in candidates:
            if c.lower().split(".")[-1] in h.lower():
                return h
    return None


def read_gleif(path: Path) -> tuple[list[dict], ImportReport]:
    """Parse a GLEIF Golden Copy CSV into {name, country, region} rows (active entities only)."""
    report = ImportReport()
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        headers = next(reader, [])
        c_lei = _find_col(headers, COL_LEI)
        c_name = _find_col(headers, COL_NAME)
        c_country = _find_col(headers, COL_COUNTRY)
        c_estatus = _find_col(headers, COL_ENTITY_STATUS)
        c_rstatus = _find_col(headers, COL_REG_STATUS)
        if not (c_name and c_country):
            raise ValueError(
                "This does not look like a GLEIF Golden Copy CSV: could not find the legal-name "
                f"and country columns. Headers seen: {headers[:8]}..."
            )
        idx = {h: i for i, h in enumerate(headers)}
        for raw in reader:
            report.read += 1
            if len(raw) < len(headers):
                continue
            estatus = raw[idx[c_estatus]] if c_estatus else "ACTIVE"
            rstatus = raw[idx[c_rstatus]] if c_rstatus else "ISSUED"
            if estatus.strip().upper() not in {"ACTIVE", ""} or \
               rstatus.strip().upper() not in {"ISSUED", "PUBLISHED", ""}:
                report.skipped_inactive += 1
                continue
            name = raw[idx[c_name]].strip()
            country = raw[idx[c_country]].strip().upper()
            if not name or not country:
                continue
            region = geo_region(country)
            rows.append({"name": name, "country": country, "region": region,
                         "lei": raw[idx[c_lei]] if c_lei else ""})
    report.kept = len(rows)
    return rows, report


def import_universe(
    gleif_csv: Path,
    seed_csv: Path,
    per_region: int | None = 1200,
    limit: int | None = None,
    only_regions: set[str] | None = None,
) -> ImportReport:
    """Merge a GLEIF CSV into the watchlist seed, capping per region and de-duplicating."""
    rows, report = read_gleif(gleif_csv)

    existing: list[dict] = []
    seen: set[str] = set()
    if seed_csv.exists():
        with seed_csv.open(encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
        seen = {normalize_name(r["seed_name"]) for r in existing}

    per_region_count: dict[str, int] = {}
    added: list[dict] = []
    for r in rows:
        region = r["region"]
        if only_regions and region not in only_regions:
            report.skipped_region += 1
            continue
        if per_region is not None and per_region_count.get(region, 0) >= per_region:
            continue
        norm = normalize_name(r["name"])
        if not norm or norm in seen:
            report.skipped_dupe += 1
            continue
        seen.add(norm)
        per_region_count[region] = per_region_count.get(region, 0) + 1
        added.append({
            "seed_name": r["name"], "country": r["country"], "segment": "",
            "homepage": "", "notes": f"LEI {r['lei']}".strip(), "strategic": "0",
            "tier": "cold", "seed_source": "gleif",
        })
        if limit is not None and len(added) >= limit:
            break

    report.added = len(added)
    report.per_region = per_region_count

    # write merged seed (existing rows first, keeping their curated flags)
    fieldnames = SEED_FIELDS
    seed_csv.parent.mkdir(parents=True, exist_ok=True)
    with seed_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in existing:
            r.setdefault("tier", "hot")
            r.setdefault("seed_source", "manual_seed")
            w.writerow(r)
        for r in added:
            w.writerow(r)
    return report


# convenience for callers/tests
ALL_GEO_REGIONS = GEO_REGIONS
