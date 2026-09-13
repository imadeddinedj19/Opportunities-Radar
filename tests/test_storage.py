from radar.models import Company, SizeBand
from radar.storage import TABLES, Store


def _company(cid="x", aliases=("x",)):
    return Company(company_id=cid, canonical_name="X AG", normalized_name="x",
                   aliases=list(aliases), size_band=SizeBand.LARGE)


def test_upsert_replaces_not_duplicates():
    s = Store(":memory:")
    assert s.upsert("companies", [_company()]) == 1
    assert s.upsert("companies", [_company(aliases=("x", "y"))]) == 1
    assert s.count("companies") == 1
    assert s.df("SELECT aliases FROM companies").iloc[0]["aliases"].tolist() == ["x", "y"]


def test_export_writes_all_tables(tmp_path):
    s = Store(":memory:")
    s.upsert("companies", [_company()])
    paths = s.export(tmp_path, fmt="csv")
    assert (tmp_path / "companies.csv").exists()
    assert len(paths) == len(TABLES)
