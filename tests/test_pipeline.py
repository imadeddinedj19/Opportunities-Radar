from radar.ingest.pipeline import run
from radar.storage import Store


def test_pipeline_processes_full_seed_and_links_events(offline_settings):
    report = run(offline_settings)
    # Acceptance: at least 100 target companies processed through the pipeline (FR-01).
    assert report.companies >= 100
    assert report.events > 0

    with Store(offline_settings.resolved_db_path) as store:
        # Acceptance/FR-04: every event has a source and a collection timestamp.
        missing = store.df(
            "SELECT count(*) n FROM events e LEFT JOIN sources s USING (source_id) "
            "WHERE s.source_id IS NULL"
        ).iloc[0]["n"]
        assert missing == 0
        null_collected = store.df(
            "SELECT count(*) n FROM events WHERE collected_at IS NULL"
        ).iloc[0]["n"]
        assert null_collected == 0
        # Every source records where and when it was retrieved (provenance).
        bad_src = store.df(
            "SELECT count(*) n FROM sources WHERE url IS NULL OR retrieved_at IS NULL"
        ).iloc[0]["n"]
        assert bad_src == 0


def test_pipeline_is_idempotent(offline_settings):
    first = run(offline_settings)
    second = run(offline_settings)
    assert first.companies == second.companies
    with Store(offline_settings.resolved_db_path) as store:
        # No duplicate rows after a second run.
        assert store.count("companies") == first.companies
        assert store.count("events") == first.events


def test_events_carry_provisional_type_and_provenance(offline_settings):
    run(offline_settings)
    with Store(offline_settings.resolved_db_path) as store:
        pg = store.df(
            "SELECT e.event_type, e.event_date, e.mention_verified, s.connector "
            "FROM events e JOIN companies c USING (company_id) JOIN sources s USING (source_id) "
            "WHERE c.canonical_name LIKE 'Partners Group%'"
        )
        assert (pg["event_type"] == "acquisition").any()
        assert pg["mention_verified"].all()          # FR-05 mention verification
        assert set(pg["connector"]) == {"google_news_rss", "gdelt"}  # multiple sources
