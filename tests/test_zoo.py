from datetime import date
from pathlib import Path

from tracking_la.sources import zoo

PAGE = (Path(__file__).parent / "fixtures" / "zoo" / "commission.html").read_bytes()
MEETING = {"body": "zoo", "date": date(2026, 9, 15), "agenda_url": zoo.PAGE + "#2026-09-15"}


def test_agenda_items_skip_standing_sections_and_keep_document_links():
    items = zoo.meeting_items(MEETING, PAGE)
    assert [i["title"] for i in items] == [
        "Presentation – Zoo Construction And Maintenance Program",
        "General Manager Reports",
        "Old Business",
    ]
    reports = items[1]
    assert reports["id"] == "zoo-2026-09-15-general-manager-reports"
    assert reports["text"].startswith(zoo.CONTEXT)
    assert len(reports["urls"]) == 3 and reports["urls"][1].endswith(".pdf")


def test_page_for_a_different_meeting_yields_nothing():
    assert zoo.meeting_items(MEETING | {"date": date(2026, 10, 20)}, PAGE) == []
