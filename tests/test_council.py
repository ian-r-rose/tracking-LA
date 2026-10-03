import json
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from lacomm.sources import council

FIXTURES = Path(__file__).parent / "fixtures" / "council"
MEETING = {
    "body": "council-plum", "date": date(2026, 9, 22), "meeting_id": 18500,
    "portal": council.PORTAL, "agenda_url": "https://lacity.primegov.com/agenda",
}


def test_meetings_by_committee_id_without_spanish_duplicates_or_cancellations():
    meetings = council.parse_meetings(json.loads((FIXTURES / "meetings.json").read_text()))
    bodies = {(m["date"].isoformat(), m["body"]) for m in meetings}
    assert ("2026-09-22", "council-plum") in bodies
    assert ("2026-10-07", "council-arts-parks") in bodies  # renamed committee, new id
    assert ("2026-10-07", "council-housing") in bodies
    assert not any(b == "council-transportation" and d == "2026-08-26" for d, b in bodies)  # cancelled
    assert len([m for m in meetings if m["meeting_id"] == 18500]) == 1  # not its SAP twin
    assert all(m["body"].startswith("council-") for m in meetings)  # full Council and other committees skipped


def test_items_carry_council_file_district_and_links():
    items = council.meeting_items(MEETING, (FIXTURES / "plum-2026-09-22.html").read_bytes())
    assert [i["item_number"] for i in items] == ["1", "2", "3", "4", "5", "6", "7"]
    second = items[1]
    assert second["id"] == "council-plum-2026-09-22-18500-2"
    assert second["text"].startswith("[Council File 25-0774; CD 15]\nDepartment of City Planning")
    assert "[ITEM(S)]" not in second["text"]
    assert second["urls"][1] == council.council_file_url("25-0774")
    assert len(second["urls"]) <= 2 + council.MAX_DOCUMENTS
    assert items[3]["text"].startswith("[Council File 16-1468-S5]")
    assert all(len(i["title"]) <= 160 for i in items)


def test_council_file_outcome_is_the_latest_action():
    html = (FIXTURES / "cf-25-0843.html").read_text()
    url = council.council_file_url("25-0843")
    # Scheduled for Council Oct 6 (not an action), so PLUM's approval is the latest.
    assert council.council_file_outcome(html, url) == {
        "status": "approved",
        "text": "Planning and Land Use Management Committee approved item(s) (Sep 22, 2026)",
        "source": url,
    }
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    assert council.council_votes(text)[date(2025, 12, 12)] == "14-1-0"
    assert council.follow_url({"urls": ["a", url]}) == url
