from datetime import date
from pathlib import Path

from tracking_la.sources import library

FIXTURES = Path(__file__).parent / "fixtures" / "library"


def test_index_skips_cancelled_meetings():
    meetings = dict(library.parse_index((FIXTURES / "meetings.html").read_text()))
    assert date(2026, 9, 10) in meetings
    assert date(2026, 9, 24) not in meetings  # cancellation notice
    assert meetings[date(2026, 9, 10)].endswith("/blc-meeting-2026-09-10")


def test_meeting_page_links_agenda_and_exhibits():
    agenda, exhibits = library.parse_meeting_page((FIXTURES / "meeting-2026-09-10.html").read_text(), library.INDEX)
    assert agenda.endswith("/2026-09/agenda.pdf")
    assert set(exhibits) == {"A", "B"}


def test_exhibits_are_the_items():
    exhibits = library.split_exhibits((FIXTURES / "agenda-2026-09-10.txt").read_text())
    assert [letter for letter, _ in exhibits] == ["A", "B"]
    assert exhibits[1][1].startswith("Recommendation to award contract to Sutherland Consulting Group")
    assert "Presentation" not in exhibits[1][1]
