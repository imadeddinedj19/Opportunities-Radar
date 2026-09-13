# Data model

Defined in `src/radar/models.py` (validated record types) and created in `src/radar/storage.py`
(DuckDB tables). Entities marked *(reserved)* are defined and have tables now so the schema is
stable, but are only populated in later segments.

| Entity | Segment | Purpose | Key fields |
|---|---|---|---|
| **Company** | S1 | One target company | `company_id`, `canonical_name`, `normalized_name`, `aliases`, `country`, `segment`, `size_band`, `employees`, `listed`, `description`, `wikidata_id`, `enrichment_confidence` |
| **Source** | S1 | Provenance: where/when a record was retrieved (FR-04) | `source_id`, `connector`, `publisher`, `url`, `query`, `retrieved_at` |
| **Event** | S1 | A detected public business event (FR-03) | `event_id`, `company_id`, `event_type`, `event_date`, `title`, `url`, `publisher`, `source_id`, `match_method`, `match_confidence`, `mention_verified`, `classification_confidence` |
| **Insight** | Insights | A distinct, deduplicated signal (one per real happening) | `insight_id`, `company_id`, `insight_type`, `canonical_title`, `event_date`, `source_count`, `connectors`, `first_seen_at`, `last_seen_at`, `is_new`, `opportunity_score` |
| **InsightSource** | Insights | One source that reported an insight (provenance) | `insight_id`, `connector`, `publisher`, `url`, `event_id`, `event_date` |
| **FeatureSnapshot** | S2 *(reserved)* | One model feature for a company at a date (FR-06) | `company_id`, `snapshot_date`, `feature_name`, `value`, `feature_version` |
| **Score** | S3 *(reserved)* | Opportunity score 0-100 (FR-07/08) | `company_id`, `model_version`, `score`, `confidence`, `rank` |
| **ProductRelevance** | S3 *(reserved)* | Relevant SIX product family (FR-09) | `company_id`, `product_family`, `relevance_score`, `evidence` |
| **Explanation** | S3 *(reserved)* | Human-readable reasons + evidence (FR-10/11) | `company_id`, `reason`, `supporting_features`, `source_ids` |
| **OutcomeLabel** | future *(reserved)* | Feedback fields for a future internal pilot (FR-14) | `opportunity_created`, `won`, `product_family`, `value`, `conversion_date` |

## Identifiers

`company_id`, `event_id` and `insight_id` are **content-derived** (a hash of the normalized
name / of company+connector+url / of company+earliest-event-title). This is what makes the
pipeline idempotent: the same input always yields the same id, so re-running upserts in place
instead of creating duplicates, and an insight keeps its id across runs so "new since last run"
is meaningful.

## Controlled vocabularies

- **EventType**: acquisition, expansion, product_launch, funding, hiring, leadership_change,
  partnership, regulatory, technology, financial_results, other, unclassified.
- **ProductFamily** (Technical Design §8): reference_data, market_data, funds_data,
  corporate_actions, regulatory_tax, esg.
- **SizeBand**: micro / small / medium / large / enterprise / unknown, derived from employee count.

## Reproducibility (NFR-03)

Every live response is written verbatim to `data/raw/<connector>/` with its URL, parameters,
status code and retrieval timestamp before parsing. `data/raw/`, `data/db/` and `data/exports/`
are reproducible outputs and are git-ignored; `data/seed/` and `data/fixtures/` are inputs and
are committed.
