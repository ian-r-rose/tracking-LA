import json
import re
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from tracking_la.sources import council

FIXTURES = Path(__file__).parent / "fixtures" / "council"
MEETING = {
    "body": "council-plum", "date": date(2026, 9, 22), "meeting_id": 18500,
    "portal": council.PORTAL, "agenda_url": "https://lacity.primegov.com/agenda",
}


def test_meetings_by_committee_id_without_spanish_duplicates_or_cancellations():
    meetings = council.parse_meetings(json.loads((FIXTURES / "meetings.json").read_text()))
    bodies = {(m["date"].isoformat(), m["body"]) for m in meetings}
    assert ("2026-09-22", "council-plum") in bodies
    assert ("2026-10-07", "council-arts-parks") in bodies  # renamed committee, new id
    assert ("2026-10-07", "council-housing") in bodies
    assert not any(b == "council-transportation" and d == "2026-08-26" for d, b in bodies)  # cancelled
    assert len([m for m in meetings if m["meeting_id"] == 18500]) == 1  # not its SAP twin
    assert all(m["body"].startswith("council") for m in meetings)  # other committees skipped


def test_full_council_has_its_extra_agendas():
    meeting = {"id": 7, "committeeId": 1, "dateTime": "2026-09-29T10:00:00", "title": "City Council Meeting",
               "documentList": [{"id": 1, "templateName": "HTML Agenda"}, {"id": 2, "templateName": "Agenda"},
                                {"id": 3, "templateName": "HTML Supplemental Agenda"}]}
    meetings = council.parse_meetings([meeting])
    assert [(m["body"], m["meeting_id"], m["agenda_url"][-1]) for m in meetings] == [
        ("council", 7, "1"), ("council", "7-supplemental", "3")]


def test_full_council_skips_routine_items_and_follows_committee_items(tmp_path):
    committee_item = tmp_path / "items" / "council-plum" / "2026" / "council-plum-2026-09-22-18500-2.json"
    committee_item.parent.mkdir(parents=True)
    committee_item.write_text(json.dumps({
        "id": "council-plum-2026-09-22-18500-2", "meeting_date": "2026-09-22",
        "text": "[Council File 25-0774; CD 15]\nDepartment of City Planning report"}))
    meeting = {"body": "council", "date": date(2026, 10, 6), "meeting_id": 2700, "portal": council.PORTAL, "agenda_url": "A"}
    items = council.meeting_items(meeting, (FIXTURES / "council-2026-10-06.html").read_bytes(), tmp_path)
    by_file = {re.match(r"\[Council File ([^;\]]+)", i["text"]).group(1): i for i in items}
    assert by_file["25-0774"]["follows"] == "council-plum-2026-09-22-18500-2"
    assert council.follow_url(by_file["25-0774"]) is None  # the committee item records Council's action
    assert "follows" not in by_file["26-1370"]  # a district's motion, straight to Council
    assert council.follow_url(by_file["26-1370"])
    assert "26-1368" not in by_file  # funding a district's World End Polio Day recognition
    assert council.SKIP_COUNCIL_ITEM.search("The City Council may recess to Closed Session, pursuant to Government Code")
    assert council.LIEN_FILE.match("26-0160-S75")


def test_revised_agendas_count():
    def meeting(templates):
        return {"id": 1, "committeeId": 2, "dateTime": "2026-09-08T10:00:00", "title": "REVISED SPECIAL - Housing Committee",
                "documentList": [{"id": n, "templateName": t} for n, t in enumerate(templates)]}

    [m] = council.parse_meetings([meeting(["HTML Special Agenda", "HTML Revised Special Agenda", "Revised Special Agenda"])])
    assert m["agenda_url"].endswith("FileId=1")  # the revision, not the original


def test_items_carry_council_file_district_and_links():
    items = council.meeting_items(MEETING, (FIXTURES / "plum-2026-09-22.html").read_bytes())
    assert [i["item_number"] for i in items] == ["1", "2", "3", "4", "5", "6", "7"]
    second = items[1]
    assert second["id"] == "council-plum-2026-09-22-18500-2"
    assert second["text"].startswith("[Council File 25-0774; CD 15]\nDepartment of City Planning")
    assert "[ITEM(S)]" not in second["text"]
    assert second["urls"][1] == council.council_file_url("25-0774")
    assert len(second["urls"]) <= 2 + council.MAX_DOCUMENTS
    assert items[3]["text"].startswith("[Council File 16-1468-S5]")
    assert all(len(i["title"]) <= 160 for i in items)


def test_council_file_outcome_is_the_latest_action():
    html = (FIXTURES / "cf-25-0843.html").read_text()
    url = council.council_file_url("25-0843")
    # Council's adoption comes after what PLUM recommended; "City Council" keeps Clerk Connect's "Council".
    assert council.council_file_outcome(html, url) == {
        "status": "approved",
        "text": "Planning and Land Use Management Committee approved item(s) (Sep 22, 2026); "
        "Council adopted item, subject to reconsideration, pursuant to Council Rule 51 (Oct 6, 2026); "
        "Council action final",
        "source": url,
        "vote": "13-1-1",
    }
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    assert council.council_votes(text)[date(2025, 12, 12)] == "14-1-0"
    # Scheduling isn't an action, and the timeline's two views don't repeat activities.
    activities = council.file_activities(BeautifulSoup(html, "html.parser"))
    assert len(activities) == len(set(activities)) == 36
    assert activities[0] == (date(2026, 10, 7), "Council action final.")
    assert council.follow_url({"urls": ["a", url]}) == url


def test_council_file_outcome_ignores_actions_before_the_meeting():
    html = (FIXTURES / "cf-25-0843.html").read_text()
    url = council.council_file_url("25-0843")
    assert council.council_file_outcome(html, url, since=date(2026, 9, 22))["text"].startswith("Planning and Land Use")
    assert council.council_file_outcome(html, url, since=date(2026, 9, 23))["text"].startswith("Council adopted")
    assert council.council_file_outcome(html, url, since=date(2026, 10, 8)) is None


def test_council_action_says_what_the_committee_recommended():
    html = (FIXTURES / "cf-26-1130.html").read_text()  # a Charter Section 245 appeal
    url = council.council_file_url("26-1130")
    # Before PLUM's Sep 8 meeting, the file was decided once already (Council asserted jurisdiction).
    assert council.council_file_outcome(html, url, since=date(2026, 9, 8)) == {
        "status": "denied",
        "text": "Planning and Land Use Management Committee denied appeal(s) (Sep 8, 2026); "
        "Council adopted item, subject to reconsideration, pursuant to Council Rule 51 (Sep 11, 2026); "
        "Council action final",
        "source": url,
        "vote": "11-0-4",
    }


def test_dashes_standing_in_for_a_council_file_are_dropped(monkeypatch):
    text = "-----\nVerbal report from the Department of Water and Power on understanding your bill."
    monkeypatch.setattr(council.primegov, "html_items", lambda meeting, html: [("1", text, [])])
    item = council.meeting_items(MEETING, b"")[0]
    assert item["title"].startswith("Verbal report") and item["text"].startswith("Verbal report")
