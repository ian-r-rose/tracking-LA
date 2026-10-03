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


def test_meeting_date_prefers_link_text_over_filename():
    assert ens.meeting_date("Board of Transportation Commissioners Meeting Agenda June 11, 2026", "x_06052026.pdf") == date(2026, 6, 11)
    assert ens.meeting_date("Agenda", "x_09102026.pdf") == date(2026, 9, 10)


def test_dwp_numbers_items_by_section_and_titles_skip_recommended_by():
    items = ens.items_from_text(ens.WATER_AND_POWER, MEETING, agenda("dwp-2026-09-22"), [])
    assert [i["item_number"] for i in items] == ["K1"] + [f"N{n}" for n in range(1, 10)]
    ge = next(i for i in items if i["item_number"] == "N3")
    assert ge["id"] == "dwp-2026-09-17-N3"
    assert ge["title"].startswith("Approval of Agreement No. 47044")
    assert ge["text"].startswith("[N. Items for Approval]\nRecommended by Power System")
    assert "$250,000,000" in ge["text"]
    # Page numbers and the next section don't leak into the last item.
    assert "Adjournment" not in items[-1]["text"]


def test_building_and_safety_haul_routes_without_owner_names():
    items = ens.split_agenda(ens.BUILDING_AND_SAFETY, agenda("bbsc-2026-07-28"))
    # Officer elections (section A) are skipped; numbering is per lettered section.
    assert [number for number, _, _ in items] == ["D1", "D2", "E1", "E2", "E3", "E4", "E5"]
    number, text, section = items[-1]
    assert section.startswith("E. PUBLIC HEARINGS regarding EXPORT-IMPORT")
    assert "SAN RAFAEL AVENUE" in text and "7,505 cubic yards" in text
    assert all("OWNER" not in text for _, text, _ in items)
    assert all("BOARD OF BUILDING AND SAFETY COMMISSIONERS  " not in text for _, text, _ in items)
