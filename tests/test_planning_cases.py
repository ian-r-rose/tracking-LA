from datetime import date
from pathlib import Path

from lacomm.sources import planning_cases

FEED = (Path(__file__).parent / "fixtures" / "planning_cases" / "newcases.json").read_bytes()
MEETING = {"commission": "planning-cases", "date": date(2026, 10, 3), "agenda_url": planning_cases.FEED}


def test_cases_for_one_project_become_one_item():
    items = {i["id"]: i for i in planning_cases.meeting_items(MEETING, FEED)}
    wilshire = items["plncase-ZA-2026-5125-ZV"]  # filed with ENV-2026-5126-EAF
    assert "plncase-ENV-2026-5126-EAF" not in items
    assert wilshire["text"].splitlines()[1] == "Case numbers: ZA-2026-5125-ZV, ENV-2026-5126-EAF"
    assert wilshire["meeting_date"] == "2026-10-02"
    assert wilshire["urls"][0].endswith("/ZA-2026-5125-ZV")
    assert len(items) < 76 and all(len(i["title"]) <= 160 for i in items.values())
