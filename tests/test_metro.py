import json
from datetime import date
from pathlib import Path

from lacomm.sources import metro

FIXTURES = Path(__file__).parent / "fixtures" / "metro"
MEETING = {"date": date(2026, 9, 24), "agenda_url": metro.items_url(3545), "page_url": "https://metro.legistar.com/MeetingDetail.aspx?LEGID=3545"}


def content() -> bytes:
    return (FIXTURES / "eventitems-3545.json").read_bytes()


def test_board_meetings_only():
    [meeting] = metro.parse_events(json.loads((FIXTURES / "events.json").read_text()))
    assert meeting["date"] == date(2026, 9, 24)
    assert meeting["agenda_url"].endswith("/events/3545/eventitems?AgendaNote=1&MinutesNote=1&Attachments=1")
    assert metro.parse_events([{"EventBodyName": "Construction Committee", "EventAgendaStatusName": "Final"}]) == []


def test_items_skip_standing_matters_and_keep_committee_context():
    items = metro.meeting_items(MEETING, content())
    numbers = [i["item_number"] for i in items]
    assert "2" not in numbers and "3" not in numbers and "4" not in numbers  # minutes, Chair, CEO
    vermont = next(i for i in items if i["item_number"] == "14")
    assert "Vermont Transit Corridor" in vermont["text"]
    assert vermont["text"].startswith("[Metro Board file 2026-0658")
    assert "COMMITTEE MADE THE FOLLOWING RECOMMENDATION" in vermont["text"]
    assert vermont["urls"][1].startswith("https://metro.legistar.com/LegislationDetail.aspx?ID=12771")
    assert len(vermont["title"]) <= 160


def test_outcomes_from_actions():
    outcomes = metro.meeting_outcomes(MEETING, content())
    assert outcomes["metro-2026-09-24-46"] == {"status": "approved", "text": "APPROVED AS AMENDED", "source": MEETING["page_url"]}
    assert outcomes["metro-2026-09-24-17"]["status"] == "approved"
    assert set(outcomes) <= {i["id"] for i in metro.meeting_items(MEETING, content())}
