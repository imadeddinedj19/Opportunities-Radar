from radar.models import EventType
from radar.normalize import guess_event_type, normalize_name, resolve_company, similarity


def test_normalize_strips_legal_form_not_distinctive_words():
    assert normalize_name("Partners Group Holding AG") == "partners group holding"
    assert normalize_name("Société Générale S.A.") == "societe generale"
    assert normalize_name("The Vanguard Group, Inc.") == "vanguard group"


def test_normalize_is_idempotent():
    once = normalize_name("Julius Bär Gruppe AG")
    assert normalize_name(once) == once


def test_similarity_matches_variants():
    assert similarity("Partners Group Holding AG", "PARTNERS GROUP") >= 90


def test_resolve_company_matches_and_rejects():
    known = {"c1": normalize_name("Partners Group Holding AG"), "c2": normalize_name("Amundi SA")}
    cid, score = resolve_company("Partners Group AG", known)
    assert cid == "c1" and score >= 88
    miss, _ = resolve_company("Totally Unrelated Startup", known)
    assert miss is None


def test_event_type_keyword_rules():
    assert guess_event_type("Firm acquires rival")[0] == EventType.ACQUISITION
    assert guess_event_type("Firm launches new fund")[0] == EventType.PRODUCT_LAUNCH
    assert guess_event_type("Ordinary board meeting")[0] == EventType.OTHER
    # provisional confidence stays low - real classification is S2
    assert guess_event_type("Firm acquires rival")[1] < 0.5
