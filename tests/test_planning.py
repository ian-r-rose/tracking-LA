import json
from datetime import date
from pathlib import Path

import httpx

from tracking_la.sources import planning
from tracking_la.store import upsert_item

FIXTURES = Path(__file__).parent / "fixtures" / "planning"
MEETING = {"body": "cpc", "date": date(2026, 9, 10), "agenda_url": "https://example/agenda"}


def agenda(doc_id: int) -> str:
    return (FIXTURES / f"agenda-{doc_id}.txt").read_text()


def test_list_meetings_skips_canceled_and_maps_commissions():
    payload = json.loads((FIXTURES / "commissions-2026.json").read_text())
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with httpx.Client(transport=transport) as client:
        meetings = planning.list_meetings(date(2026, 1, 1), date(2026, 12, 31), client)
    assert [m["body"] for m in meetings] == ["cpc", "apc-west-la", "apc-east-la", "chc"]
    assert meetings[0]["date"] == date(2026, 10, 8)


def test_cpc_agenda_includes_consent_items_and_skips_boilerplate():
    items = planning.split_agenda(agenda(81373))
    assert [number for number, _ in items] == ["5a", "6"]
    assert items[1][1].startswith("CPC-2026-3542-GPA-ZC")
    assert "16300 Foothill Boulevard" in items[1][1]
    # The item stops before the next-meeting notice and doesn't include page headers.
    assert "next regular meeting" not in items[1][1]
    assert "City Planning Commission      3" not in items[0][1]


def test_preamble_mention_of_next_meeting_does_not_end_agenda():
    items = planning.split_agenda(agenda(81461))
    assert [number for number, _ in items] == ["5", "6", "7", "8"]


def test_cultural_heritage_items_are_monuments():
    titles = [planning.item_title(text) for _, text in planning.split_agenda(agenda(81424))]
    assert titles[1] == "PROPOSED MONUMENT: CHATEAU ALTO NIDO"


def test_agenda_with_only_standing_items_has_no_items():
    assert planning.split_agenda(agenda(81333)) == []


def test_staff_report_links_matched_by_case_number():
    links = [
        "https://planning.lacity.gov/plndoc/Staff_Reports/2026/09-10-2026/CPC_2025_2081.pdf",
        "https://planning.lacity.gov/plndoc/Staff_Reports/2026/09-10-2026/CPC_2026_3542.pdf",
        "mailto:cpc@lacity.org",
    ]
    items = planning.items_from_text(MEETING, agenda(81373), links)
    assert items[1]["id"] == "cpc-2026-09-10-6"
    assert items[1]["urls"] == ["https://example/agenda", links[1]]


def test_upsert_is_idempotent_and_preserves_enrichment(tmp_path):
    item = planning.items_from_text(MEETING, agenda(81373), [])[0]
    assert upsert_item(item, tmp_path) == "new"
    assert upsert_item(item, tmp_path) == "unchanged"

    path = next(tmp_path.rglob("*.json"))
    enriched = json.loads(path.read_text()) | {"summary": "A 13-unit building", "topics": ["housing"]}
    path.write_text(json.dumps(enriched))
    assert upsert_item(item | {"text": item["text"] + " (revised)"}, tmp_path) == "updated"
    assert json.loads(path.read_text())["summary"] == "A 13-unit building"


def test_indented_item_headers_are_found_but_requested_actions_are_not():
    items = planning.split_agenda(agenda(81082))
    assert [number for number, _ in items] == ["4", "5", "6", "7", "8", "9", "10"]
    assert planning.item_title(items[2][1]).startswith("MONUMENT: MAY COMPANY GARAGE")
    # Item 5 ends where indented item 6 begins.
    assert "MAY COMPANY" not in items[1][1]


def test_minutes_outcomes_and_truncated_minutes():
    meeting = {"body": "cpc", "date": date(2026, 7, 9), "minutes_url": "M"}
    outcomes = planning.minutes_outcomes(meeting, (FIXTURES / "minutes-cpc-2026-07-09.txt").read_text())
    assert outcomes["cpc-2026-07-09-5a"]["status"] == "approved"
    assert outcomes["cpc-2026-07-09-5a"]["vote"] == "8-0"
    assert outcomes["cpc-2026-07-09-5a"]["text"].startswith("MOTION PASSED: Approve, pursuant to Chapter 1 Section 12.22 A.25")
    assert "Density Bonus" in outcomes["cpc-2026-07-09-5a"]["text"]  # continuation lines joined
    # The posted minutes stop mid-way through item 6, before its vote: record nothing rather than guess.
    assert "cpc-2026-07-09-6" not in outcomes
