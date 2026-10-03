from datetime import date
from pathlib import Path

from lacomm.sources import airports

FIXTURES = Path(__file__).parent / "fixtures" / "airports"


def test_feed_lists_board_meetings_not_committees():
    meetings = airports.parse_feed((FIXTURES / "feed.xml").read_text())
    assert meetings[0] == {
        "body": "airports",
        "date": date(2026, 9, 23),
        "agenda_url": "https://lawa.granicus.com/AgendaViewer.php?view_id=4&clip_id=1280",
    }
    assert len(meetings) == 83


def test_agenda_items_with_reports_and_no_closed_session():
    meeting = airports.parse_feed((FIXTURES / "feed.xml").read_text())[0]
    items = airports.meeting_items(meeting, (FIXTURES / "agenda-2026-09-23.html").read_bytes())
    assert [i["item_number"] for i in items] == [str(n) for n in range(1, 26)]
    first = items[0]
    assert first["id"] == "airports-2026-09-23-1"
    assert "Taxiway A West" in first["text"]
    assert first["title"].startswith("Approval of a five (5)-year Reimbursable Agreement")
    assert first["text"].startswith("[CONSENT ITEMS FOR BOARD ACTION")
    assert "MetaViewer" in first["urls"][1]
