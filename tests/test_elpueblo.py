from datetime import date
from pathlib import Path

from lacomm.sources import elpueblo

FIXTURES = Path(__file__).parent / "fixtures" / "elpueblo"


def items():
    meeting = elpueblo.parse_page((FIXTURES / "commission.html").read_text())
    return meeting, elpueblo.items_from_text(meeting, (FIXTURES / "agenda-2026-09-24.txt").read_text())


def test_page_gives_latest_meeting_without_previous_minutes():
    meeting, _ = items()
    assert meeting["date"] == date(2026, 9, 24)
    assert not any("minutes" in d["title"].lower() for d in meeting["documents"])


def test_action_items_and_matched_documents():
    _, found = items()
    assert [i["item_number"] for i in found] == [f"3.{n}" for n in range(1, 9)]
    by_number = {i["item_number"]: i for i in found}
    assert by_number["3.1"]["title"].startswith("Dept. of Transportation LADOT Holiday Moratorium")
    assert "Spring/Alameda Safety and Mobility Project" in by_number["3.1"]["text"]
    assert by_number["3.1"]["text"].startswith(elpueblo.CONTEXT)
    assert any("Olvera%20Street%20Gates" in u for u in by_number["3.8"]["urls"])
    # Acronyms match their spelled-out form: OSMAF = Olvera Street Merchants Association Foundation.
    assert any("OSMAF" in u for u in by_number["3.3"]["urls"])
    assert any("UNAM" in u for u in by_number["3.2"]["urls"])
    # Items stop before commission business.
    assert "COMMISSION BUSINESS" not in by_number["3.8"]["text"]
