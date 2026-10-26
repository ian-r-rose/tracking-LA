from datetime import date
from pathlib import Path

from tracking_la.sources import zoo

FIXTURES = Path(__file__).parent / "fixtures" / "zoo"
PAGE = (FIXTURES / "commission.html").read_bytes()
MEETING = {"body": "zoo", "date": date(2026, 9, 15), "agenda_url": zoo.PAGE + "#2026-09-15"}
OCTOBER = {"body": "zoo", "date": date(2026, 10, 20), "agenda_url": zoo.PAGE + "#2026-10-20"}


def test_agenda_items_skip_standing_sections_and_keep_document_links():
    _, lines = zoo._agenda_lines(PAGE.decode())
    items = zoo.items_from_page(MEETING, lines, None)
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


def test_lowercase_month_and_headings_with_years_and_periods():
    when, lines = zoo._agenda_lines((FIXTURES / "commission-2026-10-20.html").read_text())
    assert when == date(2026, 10, 20)
    titles = [i["title"] for i in zoo.items_from_page(OCTOBER, lines, None)]
    assert titles == [
        "2027 Zoo Commission Proposed Meeting Dates",
        "Presentation – L.A. Zoo Marketing Plan – Fy 2026/27",
        "General Manager Reports",
        "Old Business",
    ]


def test_animal_updates_report_becomes_its_own_item():
    _, lines = zoo._agenda_lines((FIXTURES / "commission-2026-10-20.html").read_text())
    url = zoo.animal_updates_url(lines)
    assert url.endswith("Animal-Transaction-Report-10.20.2026-1.pdf")
    report = (FIXTURES / "animal-updates-2026-10-20.txt").read_text()
    item = zoo.items_from_page(OCTOBER, lines, (url, report))[-1]
    assert item["id"] == "zoo-2026-10-20-animal-updates"
    assert item["urls"] == [OCTOBER["agenda_url"], url]
    assert "Chacoan peccary" in item["text"] and item["text"].startswith(zoo.CONTEXT)
