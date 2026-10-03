from datetime import date
from pathlib import Path

from lacomm.sources import trees

LISTING = (Path(__file__).parent / "fixtures" / "trees" / "pending.html").read_bytes()


def test_postings_become_items_keyed_by_posting_id():
    items = trees.meeting_items({"body": "trees", "date": date(2026, 10, 1), "agenda_url": "x"}, LISTING)
    assert len(items) == 14
    vermont = next(i for i in items if i["id"] == "trees-1070")
    assert vermont["meeting_date"] == "2026-10-02"
    assert vermont["title"].startswith("Removal of 14 street trees at 200,600,2500,7100,8500 blk S & 1025,1100,1425,1500 blk N Vermont")
    assert "\n" not in vermont["title"] and "\t" not in vermont["title"]
    assert vermont["urls"] == ["https://permits.streets.lacity.gov/treepostings/public/posting.cfm?posting_id=1070"]
