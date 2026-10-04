from datetime import date
from pathlib import Path

from tracking_la.sources import lacers
from tracking_la.sources.ens import split_agenda

FIXTURES = Path(__file__).parent / "fixtures" / "lacers"


def test_board_agendas_only_without_cache_buster():
    meetings = lacers.parse_page((FIXTURES / "agendas-and-minutes.html").read_text())
    assert meetings[0] == {
        "body": "lacers",
        "date": date(2026, 9, 22),
        "agenda_url": "https://www.lacers.org/sites/main/files/file-attachments/board_agenda_20260922_combined.pdf",
    }
    assert all("cmte" not in m["agenda_url"] for m in meetings)  # committee agendas


def test_agenda_items():
    items = split_agenda(lacers.FORMAT, (FIXTURES / "agenda-2026-09-22.txt").read_text())
    assert [n for n, _, _ in items] == ["IIIA", "IIIB", "VB", "VC", "VD", "VIA", "VIIB"]
