from datetime import date
from pathlib import Path

import httpx

from tracking_la.sources import zoo

FIXTURES = Path(__file__).parent / "fixtures" / "zoo"
AGENDA_URL = "https://ens.lacity.org/zoo/zooagendas/zoozooagendas1504200801_10202026.pdf"
REPORT_URL = "https://lazoo.org/wp-content/uploads/2026/10/4-Zoo-Commission-Animal-Transaction-Report-10.20.2026-1.pdf"
OCTOBER = {"body": "zoo", "date": date(2026, 10, 20), "agenda_url": AGENDA_URL}


def test_agenda_items_skip_the_sidebar_and_standing_items():
    items = zoo.agenda_items(OCTOBER, (FIXTURES / "agenda-2026-10-20.txt").read_text())
    assert [i["title"] for i in items] == [
        "2027 Zoo Commission Proposed Meeting Dates",
        "Presentation - L.A. Zoo Marketing Plan - Fy 2026/27",
        "General Manager Reports",
        "Old Business",
    ]
    reports = items[2]
    assert reports["id"] == "zoo-2026-10-20-general-manager-reports"
    assert reports["text"].splitlines() == [zoo.CONTEXT, "GENERAL MANAGER REPORTS", "  a. Animal Updates", "", "  b. Zoo Director Updates"]
    assert reports["urls"] == [AGENDA_URL]


def test_agenda_items_with_a_sidebar_line_beside_an_item():
    august = OCTOBER | {"date": date(2026, 8, 18)}
    items = zoo.agenda_items(august, (FIXTURES / "agenda-2026-08-18.txt").read_text())
    assert [i["item_number"] for i in items] == [
        "election-of-officers",
        "presentation-duttenhaver-conservation-field-study-",  # cut at 50 characters
        "presentation-conservation-summer-internship-progra",
        "general-manager-reports",
        "old-business",
    ]
    assert "Chief Executive" not in items[3]["text"]


def test_animal_updates_url_only_for_the_meeting_the_page_shows():
    page = (FIXTURES / "commission-2026-10-20.html").read_text()  # its date has a lowercase month
    assert zoo.animal_updates_url(page, date(2026, 10, 20)) == REPORT_URL
    assert zoo.animal_updates_url(page, date(2026, 9, 15)) is None
    september = (FIXTURES / "commission.html").read_text()
    assert zoo.animal_updates_url(september, date(2026, 9, 15)).endswith("Animal-Transaction-Report-9.18.2026.pdf")


def mock_fetch(monkeypatch, respond):
    monkeypatch.setattr(zoo, "http_client", lambda **kw: httpx.Client(transport=httpx.MockTransport(respond)))
    texts = {b"agenda": (FIXTURES / "agenda-2026-10-20.txt").read_text(), b"report": (FIXTURES / "animal-updates-2026-10-20.txt").read_text()}
    monkeypatch.setattr(zoo, "pdf_text", lambda data: texts[data])


def test_animal_updates_report_becomes_its_own_item(monkeypatch):
    def respond(request):
        if str(request.url) == zoo.PAGE:
            return httpx.Response(200, content=(FIXTURES / "commission-2026-10-20.html").read_bytes())
        assert str(request.url) == REPORT_URL
        return httpx.Response(200, content=b"report")

    mock_fetch(monkeypatch, respond)
    item = zoo.meeting_items(OCTOBER, b"agenda")[-1]
    assert item["id"] == "zoo-2026-10-20-animal-updates"
    assert item["urls"] == [AGENDA_URL, REPORT_URL]
    assert "Chacoan peccary" in item["text"] and item["text"].startswith(zoo.CONTEXT)


def test_refused_report_leaves_the_agenda_items(monkeypatch, capsys):
    mock_fetch(monkeypatch, lambda request: httpx.Response(403))
    items = zoo.meeting_items(OCTOBER, b"agenda")
    assert len(items) == 4 and items[-1]["item_number"] == "old-business"
    assert "pending: zoo Animal Updates for 2026-10-20" in capsys.readouterr().out


def test_meetings_are_fetched_again_until_their_report_comes_through(tmp_path):
    def respond(request):
        return httpx.Response(200, text='<a href="zooagendas/zoozooagendas1504200017_09152026.pdf">Zoo Commission Agenda - September 2026</a>'
                                        '<a href="zooagendas/zoozooagendas1504200801_10202026.pdf">Zoo Commission Agenda - October 2026</a>')

    folder = tmp_path / "items" / "zoo" / "2026"
    folder.mkdir(parents=True)
    (folder / "zoo-2026-09-15-animal-updates.json").write_text("{}")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        meetings = zoo.list_meetings(date(2026, 9, 1), date(2026, 10, 31), client, tmp_path)
    assert [(m["date"], m["agenda_url"], m.get("refetch")) for m in meetings] == [
        (date(2026, 9, 15), "https://ens.lacity.org/zoo/zooagendas/zoozooagendas1504200017_09152026.pdf", None),
        (date(2026, 10, 20), AGENDA_URL, True),
    ]
