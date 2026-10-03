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


def test_building_and_safety_haul_routes():
    items = ens.split_agenda(ens.BUILDING_AND_SAFETY, agenda("bbsc-2026-07-28"))
    # Officer elections (section A) are skipped; numbering is per lettered section.
    assert [number for number, _, _ in items] == ["D1", "D2", "E1", "E2", "E3", "E4", "E5"]
    number, text, section = items[-1]
    assert section.startswith("E. PUBLIC HEARINGS regarding EXPORT-IMPORT")
    assert "SAN RAFAEL AVENUE" in text and "7,505 cubic yards" in text
    assert all("BOARD OF BUILDING AND SAFETY COMMISSIONERS  " not in text for _, text, _ in items)


def test_police_fire_animal_letter_items_within_numbered_sections():
    police = ens.split_agenda(ens.POLICE, agenda("police-2026-09-29"))
    assert [n for n, _, _ in police] == ["4A", "4B", "4C", "4D", "4E", "4F", "4G", "4H", "4I", "5A", "5B"]
    assert all("PUBLIC EMPLOYEE" not in t for _, t, _ in police)  # closed session dropped
    fire = ens.split_agenda(ens.FIRE, agenda("fire-2026-09-15"))
    assert [n for n, _, _ in fire] == ["4A", "4B", "4C"]  # oral reports skipped
    assert all("EQUAL EMPLOYMENT" not in t for _, t, _ in fire)
    animal = ens.split_agenda(ens.ANIMAL_SERVICES, agenda("animal-2026-09-08"))
    assert [n for n, _, _ in animal] == ["3A", "3B", "3C", "3D"]  # minutes approval skipped
    assert "Please join us" not in animal[2][1]


def test_cancellation_notice_drops_the_agenda_beside_it():
    class Listing:
        text = """
        <a href="a/x_09222026.pdf">Board Meeting - September 22, 2026</a>
        <a href="a/y_09222026.pdf">Cancellation Notice - Board Meeting - September 22, 2026</a>
        <a href="a/z_09082026.pdf">Board Meeting - September 8, 2026</a>
        <a href="a/s_09222026.pdf">Special Board Meeting - September 22, 2026</a>
        <a href="a/w_05052026.pdf">Meeting Agenda - Cancellations &amp; Additions</a>
        <a href="a/v_05052026.pdf">Meeting Agenda</a>
        """
        def raise_for_status(self): pass

    class Client:
        def get(self, url): return Listing()

    meetings = ens.list_meetings(ens.ANIMAL_SERVICES, date(2026, 1, 1), date(2026, 12, 31), Client())
    assert [m["agenda_url"][-14:] for m in meetings] == ["z_09082026.pdf", "s_09222026.pdf", "v_05052026.pdf"]


def test_ethics_and_fire_police_pensions():
    ethics = ens.split_agenda(ens.ETHICS, agenda("ethics-2026-06-17"))
    assert [n for n, _, _ in ethics] == [str(n) for n in range(5, 15)]  # opening and closing items skipped
    assert ethics[0][2] == "Action Items"
    lafpp = ens.split_agenda(ens.FIRE_AND_POLICE_PENSIONS, agenda("lafpp-2026-10-01"))
    assert [n for n, _, _ in lafpp] == ["C1", "D1", "D2", "D3"]  # closed session and standing items dropped
