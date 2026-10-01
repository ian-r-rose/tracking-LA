from datetime import date
from pathlib import Path

from lacomm.sources import rap

FIXTURES = Path(__file__).parent / "fixtures" / "rap"


def meetings():
    return rap.parse_year_page((FIXTURES / "year-2026.html").read_text())


def test_year_page_lists_meetings_with_minutes_and_documents():
    oct1, sep17 = meetings()[:2]
    assert oct1["date"] == date(2026, 10, 1)
    assert oct1["agenda_url"].endswith("/oct01/rap-meeting-agenda-10-1-2026.pdf")
    assert oct1["minutes_url"] is None  # not posted yet
    assert sep17["minutes_url"].startswith("https://recreation.parks.lacity.gov/")
    titles = [d["title"] for d in oct1["documents"]]
    assert "26-221" in titles and "Arroyo Seco Water Reuse Project motion" in titles


def test_items_include_board_reports_and_extra_documents_but_not_constituent_letters():
    sep17 = meetings()[1]
    extra = {d["url"]: "some text" for d in sep17["documents"]}
    items = rap.items_from_meeting(sep17, (FIXTURES / "agenda-2026-09-17.txt").read_text(), extra)
    ids = [i["id"] for i in items]
    sycamore = next(i for i in items if i["id"] == "rap-2026-09-17-26-213")
    assert sycamore["title"].startswith("Sycamore Grove Park Master Plan")
    assert sycamore["urls"] == [sep17["agenda_url"], sep17["minutes_url"], next(d["url"] for d in sep17["documents"] if d["title"] == "26-213")]
    assert "rap-2026-09-17-information-report-log-with-vc-numbers-9-17-26" in ids
    assert not any("constituent" in i for i in ids)
    # The last report stops at the next numbered agenda section.
    assert "COMMISSION TASK FORCE" not in items[10]["text"]


def test_motion_becomes_its_own_item():
    oct1 = meetings()[0]
    motion = next(d for d in oct1["documents"] if "motion" in d["title"])
    items = rap.items_from_meeting(oct1, (FIXTURES / "agenda-2026-10-01.txt").read_text(), {motion["url"]: "MOTION ..."})
    item = next(i for i in items if i["id"] == "rap-2026-10-01-arroyo-seco-water-reuse-project-motion")
    assert item["text"].startswith("[Arroyo Seco Water Reuse Project motion]\nMOTION")
