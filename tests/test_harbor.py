from datetime import date
from pathlib import Path

from tracking_la.sources import harbor

FIXTURES = Path(__file__).parent / "fixtures" / "harbor"


def test_archive_lists_board_agendas_not_committees():
    meetings = harbor.parse_archive((FIXTURES / "archive.html").read_text())
    assert meetings[0] == {
        "body": "harbor",
        "date": date(2026, 9, 30),
        "kind": "special",
        "agenda_url": "https://portoflosangeles.org/commission/agenda-archive-and-videos/agendas/2026/09302026-special-agenda",
    }
    assert not any("committee" in m["agenda_url"] for m in meetings)


def test_items_get_only_their_own_documents():
    meeting = next(m for m in harbor.parse_archive((FIXTURES / "archive.html").read_text())
                   if m["date"] == date(2026, 9, 10) and m["kind"] == "regular")
    items = harbor.meeting_items(meeting, (FIXTURES / "agenda-2026-09-10-regular.html").read_bytes())
    assert [i["id"] for i in items] == [f"harbor-2026-09-10-regular-{n}" for n in range(1, 5)]
    first = items[0]
    assert first["title"].startswith("APPROVE REQUEST FOR 2026-2029 ON-CALL MULTIMODAL PLANNING")
    assert "$1,397,000" in first["text"] and "Recommendation" in first["text"]
    for n, item in enumerate(items, start=1):
        assert all(f"/{n:02d}_" in u for u in item["urls"][1:])
