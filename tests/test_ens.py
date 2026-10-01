from datetime import date
from pathlib import Path

from lacomm.sources import ens

FIXTURES = Path(__file__).parent / "fixtures" / "ens"
MEETING = {"date": date(2026, 9, 17), "agenda_url": "https://example/agenda"}


def agenda(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


def test_transportation_skips_admin_items_and_keeps_sections():
    items = ens.split_agenda(ens.TRANSPORTATION, agenda("transportation-2026-09-10"))
    assert [number for number, _, _ in items] == ["7", "8", "9", "10", "11"]
    assert items[2][2] == "CONSENT ITEMS"
    assert "PREFERENTIAL PARKING DISTRICT NO. 338" in items[2][1]
    assert items[4][2] == "EXECUTIVE SESSION"
    # Page headers and the trailing section heading don't leak into item text.
    assert "COMMISSIONERS AGENDA" not in items[3][1]
    assert "EXECUTIVE SESSION" not in items[3][1]


def test_rap_board_reports_and_report_links():
    links = [
        "www.laparks.org/sites/default/files/pdf/commissioner/2026/sep17/26-213.pdf",
        "www.laparks.org/sites/default/files/pdf/commissioner/2026/sep17/26-214.pdf",
    ]
    items = ens.items_from_text(ens.RECREATION_AND_PARKS, MEETING, agenda("rap-2026-09-17"), links)
    assert [i["item_number"] for i in items] == [f"26-{n}" for n in range(207, 218)]
    sycamore = next(i for i in items if i["item_number"] == "26-213")
    assert sycamore["id"] == "rap-2026-09-17-26-213"
    assert sycamore["title"].startswith("Sycamore Grove Park Master Plan")
    assert sycamore["urls"] == ["https://example/agenda", "https://" + links[0]]
    # The last report stops at the next numbered agenda section.
    assert "COMMISSION TASK FORCE" not in items[-1]["text"]


def test_meeting_date_prefers_link_text_over_filename():
    assert ens.meeting_date("Board of Transportation Commissioners Meeting Agenda June 11, 2026", "x_06052026.pdf") == date(2026, 6, 11)
    assert ens.meeting_date("Agenda", "x_09102026.pdf") == date(2026, 9, 10)
