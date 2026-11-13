import json
import re
from datetime import date
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from tracking_la.sources import council

FIXTURES = Path(__file__).parent / "fixtures" / "council"
MEETING = {
    "body": "council-plum", "name": "Planning and Land Use Management Committee", "date": date(2026, 11, 10),
    "meeting_id": "20261110", "agenda_url": "https://example.org/2026-11-10-planning-and-land-use-management-v1.pdf",
}


def lms_meetings():
    feed = json.loads((FIXTURES / "lms-meetings.json").read_text())  # two pages of the LMS's list, trimmed
    return council.parse_meetings(feed["upcoming"] + feed["past"])


def test_meetings_of_watched_bodies_without_cancellations():
    meetings = lms_meetings()
    bodies = {(m["date"].isoformat(), m["body"]) for m in meetings}
    assert ("2026-11-10", "council") in bodies
    assert ("2026-11-10", "council-plum") in bodies
    assert ("2026-11-13", "council-environment") in bodies  # upcoming
    assert ("2026-11-11", "council") not in bodies  # a notice of cancellation
    assert ("2026-11-04", "council-transportation") not in bodies  # cancelled, with the notice as a second agenda
    assert {m["body"] for m in meetings} <= set(council.BODIES.values())  # other committees skipped
    assert all(m["agenda_url"].endswith(".pdf") for m in meetings)


def test_a_rescheduled_meeting_keeps_its_id():
    [moved] = [m for m in lms_meetings() if m["body"] == "council-transportation" and m["date"] == date(2026, 11, 18)]
    assert moved["meeting_id"] == "20261104"  # first scheduled for November 4
    assert council.meeting_id("2026-10-30-council-3", "council") == "20261030-3"


def test_full_council_has_its_extra_agendas():
    by_day = {}
    for m in lms_meetings():
        if m["body"] == "council":
            by_day.setdefault(m["date"].isoformat(), []).append(m["meeting_id"])
    assert sorted(by_day["2026-10-30"]) == ["20261030", "20261030-3"]  # regular and special, separate meetings
    assert sorted(by_day["2026-10-23"]) == ["20261023", "20261023-2", "20261023-3"]  # imported: under `agendas`


def test_revised_agenda_is_a_new_url():
    [revised] = [m for m in lms_meetings() if m["body"] == "council" and m["date"] == date(2026, 11, 10)]
    assert revised["agenda_url"].endswith("2026-11-10-council-v2.pdf")  # not seen before, so fetched again


def test_meetings_are_listed_back_to_the_start_and_no_further():
    feed = json.loads((FIXTURES / "lms-meetings.json").read_text())
    asked = []

    def respond(request):
        asked.append(dict(request.url.params))
        page = int(request.url.params["page"])
        past = [m for m in feed["past"] if m["body"] == request.url.params["body"]][(page - 1) * 2 : page * 2]
        return httpx.Response(200, json={"upcoming": {"meetings": []}, "past": {"meetings": past, "nextUrl": "more"}})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    raw = council.lms_meetings("council", date(2026, 11, 5), client)
    assert [a["page"] for a in asked] == ["1", "2"] and asked[0]["format"] == "json"
    assert min(m["date"] for m in raw) < "2026-11-05"


def test_a_challenged_list_of_meetings_fails():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(202, headers={"x-amzn-waf-action": "challenge"})))
    with pytest.raises(council.Challenged):
        council.list_meetings(date(2026, 11, 1), date(2026, 12, 1), client)


def test_meetings_the_portal_recorded_arent_listed_again():
    feed = json.loads((FIXTURES / "lms-meetings.json").read_text())
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "upcoming": {"meetings": []}, "past": {"meetings": feed["past"], "nextUrl": None}})))
    meetings = council.list_meetings(date(2026, 10, 1), date(2026, 12, 1), client)
    assert meetings and min(m["date"] for m in meetings) >= council.LMS_SINCE


@pytest.fixture(autouse=True)
def agendas_as_text(monkeypatch):
    """Agenda fixtures are the PDFs' text (pdftotext -layout), since PDFs aren't kept in the repository."""
    monkeypatch.setattr(council, "pdf_text", lambda data: data.decode())


def test_full_council_skips_routine_items_and_follows_committee_items(tmp_path):
    committee_item = tmp_path / "items" / "council-plum" / "2026" / "council-plum-2026-09-22-18500-2.json"
    committee_item.parent.mkdir(parents=True)
    committee_item.write_text(json.dumps({
        "id": "council-plum-2026-09-22-18500-2", "meeting_date": "2026-09-22",
        "text": "[Council File 26-1287; CD 15]\nDepartment of City Planning report"}))
    meeting = {"body": "council", "name": "City Council", "date": date(2026, 10, 30), "meeting_id": "20261030-3", "agenda_url": "A"}
    items = council.meeting_items(meeting, (FIXTURES / "council-2026-10-30-special.txt").read_bytes(), tmp_path)
    by_file = {re.match(r"\[Council File ([^;\]]+)", i["text"]).group(1): i for i in items}
    assert by_file["26-1287"]["follows"] == "council-plum-2026-09-22-18500-2"
    assert council.follow_url(by_file["26-1287"]) is None  # the committee item records Council's action
    assert "follows" not in by_file["26-1496"]
    assert council.follow_url(by_file["26-1496"]) == council.council_file_url("26-1496")
    assert by_file["26-1496"]["id"] == "council-2026-10-30-20261030-3-2"
    assert by_file["26-1496"]["text"].splitlines()[1].startswith("[Items for which Public Hearings Have")  # its section
    assert council.SKIP_COUNCIL_ITEM.search("The City Council may recess to Closed Session, pursuant to Government Code")
    assert council.SKIP_COUNCIL_ITEM.search("MOTION relative to funding for services in connection with the World Polio Day recognition")
    assert council.LIEN_FILE.match("26-0160-S75")


def test_items_carry_council_file_district_and_links():
    items = council.meeting_items(MEETING, (FIXTURES / "plum-2026-11-10.txt").read_bytes())
    assert [i["item_number"] for i in items] == [str(n) for n in range(1, 12)]
    first, second = items[0], items[1]
    assert first["id"] == "council-plum-2026-11-10-20261110-1"
    assert first["text"].startswith("[Council File 26-0734-S1; CD 11]\nPreviously assessed Venice Auxiliary Pumping Plant")
    assert "Page 1 of 7" not in first["text"]  # a page footer falls in the middle of the item
    assert "an appeal filed by Kenya Lee, from the determination" in first["text"]  # and its paragraph stays whole
    assert "Applicant: Department of Public Works (DPW) and LA Sanitation and Environment" in first["text"].splitlines()
    assert "Community Impact Statement:\nYes" in first["text"]
    assert second["text"].startswith("[Council File 26-1571]\nMotion (Blumenfield - Hernandez)")  # Citywide: no district
    assert second["urls"] == [MEETING["agenda_url"], council.council_file_url("26-1571")]
    assert "[Item(s)]" not in second["text"]
    assert "Notice to Paid Representatives" not in items[-1]["text"]  # the agenda's closing notices
    assert all(len(i["title"]) <= 160 for i in items)


AGENDA = """
Items for which Public Hearings Have Not Been Held - (10 Votes Required for           2 items
Consideration)

  Item 1 ·                                                                          Citywide

Verbal report from the Department of Water and Power on understanding your bill.

  Item 2 · CF 26-0976                                                                  CD 15

PUBLIC WORKS COMMITTEE REPORT relative to the name of the private
driveway at 6th Street being established as Sampson Circle.

Recommendation(s) for Council action:
    1. FIND that the name establishment is exempt.



City Council                         - November 10, 2026 -                      Page 6 of 28
Fiscal impact statement       The City Engineer reports that a fee was collected pursuant to Section
                              18.09 of the Los Angeles Municipal Code.
Community impact              None submitted
statement

MOTIONS FOR POSTING AND REFERRAL
COUNCIL ADJOURNMENT
"""


def test_agenda_text_becomes_items_with_sections_recommendations_and_fields():
    (n1, file1, where1, section1, lines1), (n2, file2, where2, section2, lines2) = council.agenda_items(AGENDA, "City Council")
    assert (n1, file1, where1) == ("1", None, None)  # no Council File
    assert lines1 == ["Verbal report from the Department of Water and Power on understanding your bill."]
    assert section1 == section2 == "Items for which Public Hearings Have Not Been Held - (10 Votes Required for Consideration)"
    assert (n2, file2, where2) == ("2", "26-0976", "CD 15")
    assert lines2 == [
        "PUBLIC WORKS COMMITTEE REPORT relative to the name of the private driveway at 6th Street being established as Sampson Circle.",
        "Recommendation(s) for Council action:",
        "1. FIND that the name establishment is exempt.",
        "Fiscal Impact Statement:",
        "The City Engineer reports that a fee was collected pursuant to Section 18.09 of the Los Angeles Municipal Code.",
        "Community Impact Statement:",
        "None submitted",
    ]


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


def test_council_action_reads_what_council_did():
    # Since the switch to the LMS, Council's action is a second paragraph under "City Council action:".
    html = (FIXTURES / "cf-26-1424.html").read_text()
    url = council.council_file_url("26-1424")
    assert council.council_file_outcome(html, url, since=date(2026, 10, 21)) == {
        "status": "approved",
        "text": "Transportation Committee approved item(s) (Oct 21, 2026); "
        "Council action: Adopted (Oct 27, 2026); Council action final",
        "source": url,
        "vote": "13-0-2",
    }


def test_a_page_that_isnt_a_file_page_is_refused():
    html = "<html><body><main>Something went wrong. Please try again.</main></body></html>"
    with pytest.raises(council.NotAFilePage):
        council.council_file_outcome(html, council.council_file_url("26-1424"))


def test_a_committee_named_in_councils_action_isnt_the_committees_action():
    activities = [
        "Council action final.",
        "Council action: Adopted, Forthwith: Adopted Planning and Land Use Committee Report and Ordinance",
        "Planning and Land Use Management Committee approved item(s).",
    ]
    assert [bool(council.COMMITTEE_ACTION.match(a)) for a in activities] == [False, False, True]
