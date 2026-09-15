-- Opportunities Radar - Supabase / Postgres schema
-- Apply in the Supabase SQL editor, or connect with RADAR_DB_URL and the tool creates
-- these tables automatically (idempotent CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS companies (
    company_id VARCHAR PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL,
    aliases TEXT[],
    domain VARCHAR,
    country VARCHAR,
    industry VARCHAR,
    segment VARCHAR,
    size_band VARCHAR,
    employees INTEGER,
    listed BOOLEAN,
    description VARCHAR,
    region VARCHAR,
    strategic BOOLEAN,
    tier VARCHAR,
    wikidata_id VARCHAR,
    enrichment_confidence DOUBLE PRECISION,
    seed_source VARCHAR,
    updated_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR PRIMARY KEY,
    connector VARCHAR NOT NULL,
    publisher VARCHAR,
    url VARCHAR NOT NULL,
    query VARCHAR,
    retrieved_at TIMESTAMPTZ NOT NULL,
    from_fixture BOOLEAN
);
CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR PRIMARY KEY,
    company_id VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    event_date DATE,
    title VARCHAR NOT NULL,
    text VARCHAR,
    url VARCHAR,
    publisher VARCHAR,
    language VARCHAR,
    source_id VARCHAR NOT NULL,
    match_method VARCHAR,
    match_confidence DOUBLE PRECISION,
    mention_verified BOOLEAN,
    classification_confidence DOUBLE PRECISION,
    collected_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id VARCHAR PRIMARY KEY,
    company_id VARCHAR NOT NULL,
    insight_type VARCHAR NOT NULL,
    canonical_title VARCHAR NOT NULL,
    event_date DATE,
    source_count INTEGER,
    connectors TEXT[],
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    is_new BOOLEAN,
    opportunity_score DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS insight_sources (
    insight_id VARCHAR NOT NULL,
    connector VARCHAR NOT NULL,
    publisher VARCHAR,
    url VARCHAR,
    event_id VARCHAR NOT NULL,
    event_date DATE,
    PRIMARY KEY (insight_id, event_id)
);
CREATE TABLE IF NOT EXISTS feature_snapshots (
    company_id VARCHAR NOT NULL,
    snapshot_date DATE NOT NULL,
    feature_name VARCHAR NOT NULL,
    value DOUBLE PRECISION,
    feature_version VARCHAR,
    PRIMARY KEY (company_id, snapshot_date, feature_name, feature_version)
);
CREATE TABLE IF NOT EXISTS scores (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION,
    score_date TIMESTAMPTZ,
    rank INTEGER,
    PRIMARY KEY (company_id, model_version)
);
CREATE TABLE IF NOT EXISTS score_history (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    run_at TIMESTAMPTZ NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    rank INTEGER,
    PRIMARY KEY (company_id, model_version, run_at)
);
CREATE TABLE IF NOT EXISTS product_relevance (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    product_family VARCHAR NOT NULL,
    relevance_score DOUBLE PRECISION NOT NULL,
    evidence VARCHAR,
    PRIMARY KEY (company_id, model_version, product_family)
);
CREATE TABLE IF NOT EXISTS explanations (
    company_id VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    supporting_features TEXT[],
    source_ids TEXT[],
    PRIMARY KEY (company_id, model_version)
);
CREATE TABLE IF NOT EXISTS outcome_labels (
    company_id VARCHAR PRIMARY KEY,
    opportunity_created BOOLEAN,
    opportunity_stage VARCHAR,
    won BOOLEAN,
    product_family VARCHAR,
    value DOUBLE PRECISION,
    conversion_date DATE,
    label_source VARCHAR
);
