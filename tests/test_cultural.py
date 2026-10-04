import json
from datetime import date
from pathlib import Path

from tracking_la.sources import cultural

TABLE = json.loads((Path(__file__).parent / "fixtures" / "cultural" / "view.json").read_text())


def test_meetings_from_view_skip_cancelled_dates():
    meetings = cultural.parse_view(TABLE)
    dates = [m["date"] for m in meetings]
    assert date(2026, 9, 9) not in dates  # agenda posted, then cancelled
    assert date(2026, 8, 12) in dates
    aug = next(m for m in meetings if m["date"] == date(2026, 8, 12))
    assert aug["agenda_file"] == "CAC REGULAR MEETING Agenda 8-12-26_FINAL.docx.pdf"


def test_one_item_per_meeting_saying_contents_unavailable():
    aug = next(m for m in cultural.parse_view(TABLE) if m["date"] == date(2026, 8, 12))
    [item] = cultural.meeting_items(aug, b"")
    assert item["id"] == "cac-2026-08-12-meeting"
    assert item["text"].startswith(cultural.NOTE)
    assert item["title"] == "Cultural Affairs Commission meeting, August 12, 2026"
