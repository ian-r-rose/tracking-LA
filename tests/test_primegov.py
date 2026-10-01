import json
from datetime import date
from pathlib import Path

import httpx

from lacomm.sources import primegov

FIXTURES = Path(__file__).parent / "fixtures" / "primegov"
MEETING = {"commission": "bpw", "date": date(2026, 9, 30), "meeting_id": 2835, "agenda_url": "https://example/agenda"}


def test_items_carry_section_matter_id_and_report_link():
    items = primegov.meeting_items(MEETING, (FIXTURES / "bpw-agenda-2026-09-30.html").read_bytes())
    assert [i["item_number"] for i in items] == [str(n) for n in range(1, 10)]
    first = items[0]
    assert first["id"] == "bpw-2026-09-30-2835-1"
    assert first["title"] == "BPW-2026-0506"
    assert first["text"].startswith("[CONSENT ITEM]\nBPW-2026-0506")
    assert "Avalon Boulevard Improvements" in first["text"]
    assert first["urls"][1].startswith("https://dpwlacity.primegov.com/api/compilemeetingattachmenthistory/")
    assert items[2]["text"].startswith("[BUREAU OF ENGINEERING]")


def test_list_meetings_keeps_board_meetings_with_html_agendas():
    archived = json.loads((FIXTURES / "archived-2026.json").read_text())

    def handler(request):
        return httpx.Response(200, json=archived if "Archived" in request.url.path else [])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        meetings = primegov.list_meetings(date(2026, 1, 1), date(2026, 12, 31), client)
    assert meetings and {m["commission"] for m in meetings} == {"bpw"}
    assert all("compiledMeetingDocumentFileId" in m["agenda_url"] for m in meetings)


def test_commission_slug():
    assert primegov.commission_slug("BPW - Regular Meeting") == "bpw"
    assert primegov.commission_slug("CFAC - Community Forest Advisory Committee (CFAC) Meeting") is None
    assert primegov.commission_slug("BPW - Official Notice") is None
    assert primegov.commission_slug("Canceled - BPW - Special Meeting") is None
    assert primegov.commission_slug("Special Town Hall Meeting - CD 6") is None
