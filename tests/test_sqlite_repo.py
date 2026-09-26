from pathlib import Path

from scraper_app.db.models import Association, new_id
from scraper_app.db.repository import Repository
from scraper_app.scheduler.runner import current_hour_bucket


def test_hourly_cap_and_random_pick(tmp_path: Path):
    repo = Repository(sqlite_path=tmp_path / "t.db")
    assoc = Association(id=new_id(), name="Test", website_url="http://example", max_per_hour=2)
    repo.upsert_association(assoc)
    repo.upsert_discovered_records(
        assoc.id,
        [
            {"source_url": "http://example/1", "external_id": "1"},
            {"source_url": "http://example/2", "external_id": "2"},
            {"source_url": "http://example/3", "external_id": "3"},
        ],
    )
    assert len(repo.list_records(assoc.id, status="pending")) == 3
    picked = {repo.pick_random_pending(assoc.id).source_url for _ in range(20)}
    assert picked <= {"http://example/1", "http://example/2", "http://example/3"}
    assert len(picked) >= 1

    bucket = current_hour_bucket()
    assert repo.get_hour_count(assoc.id, bucket) == 0
    assert repo.increment_hour_count(assoc.id, bucket) == 1
    assert repo.increment_hour_count(assoc.id, bucket) == 2
    assert repo.get_hour_count(assoc.id, bucket) == 2


def test_scraped_records_json(tmp_path: Path):
    repo = Repository(sqlite_path=tmp_path / "t.db")
    assoc = Association(id=new_id(), name="A", website_url="http://x")
    repo.upsert_association(assoc)
    data = {
        "General Profile Information": {"Profile Type": "Member"},
        "Contacts": [{"Name": "Sam"}],
    }
    saved = repo.save_scraped_record(assoc.id, "http://x/p1", data)
    rows = repo.list_scraped_records(assoc.id)
    assert len(rows) == 1
    assert rows[0].record_id == saved.record_id
    assert rows[0].scraped_data["Contacts"][0]["Name"] == "Sam"
