"""Board of Library Commissioners (Los Angeles Public Library).

lapl.org lists meetings, each with its own page linking the agenda PDF and the
exhibits (staff reports) it covers. The Board's decisions are the exhibits listed
under the City Librarian's reports ("Exhibit A / Recommendation to ..."), so each
exhibit becomes an item.
"""

import re
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from lacomm.pdf import normalize_space, pdf_text

INDEX = "https://www.lapl.org/board-library-commissioners/meetings"
MEETING_PAGE = re.compile(r"/board-library-commissioners/meetings/blc-meeting-(\d{4}-\d{2}-\d{2})")


def parse_index(html: str) -> list[tuple[date, str]]:
    """(date, meeting page URL) for meetings that weren't cancelled."""
    meetings = {}
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=MEETING_PAGE):
        if "cancel" in a.get_text().lower():
            continue
        day = date.fromisoformat(MEETING_PAGE.search(a["href"]).group(1))
        meetings[day] = urljoin(INDEX, a["href"])
    return sorted(meetings.items(), reverse=True)


def parse_meeting_page(html: str, page_url: str) -> tuple[str | None, dict[str, str]]:
    """The agenda PDF's URL and {exhibit letter: URL}."""
    agenda, exhibits = None, {}
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        if text == "Agenda" and a["href"].lower().endswith(".pdf"):
            agenda = urljoin(page_url, a["href"])
        elif m := re.fullmatch(r"Exhibit ([A-Z])", text):
            exhibits[m.group(1)] = urljoin(page_url, a["href"])
    return agenda, exhibits


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(INDEX)
    resp.raise_for_status()
    meetings = []
    for day, page_url in parse_index(resp.text):
        if not start <= day <= end:
            continue
        page = client.get(page_url)
        page.raise_for_status()
        agenda, exhibits = parse_meeting_page(page.text, page_url)
        if agenda:
            meetings.append({"commission": "library", "date": day, "agenda_url": agenda, "page_url": page_url, "exhibits": exhibits})
    return meetings


def split_exhibits(agenda_text: str) -> list[tuple[str, str]]:
    """(letter, recommendation text) for each exhibit listed on the agenda."""
    exhibits: list[tuple[str, list[str]]] = []
    current = None
    for line in agenda_text.replace("​", "").splitlines():
        stripped = line.strip()
        if m := re.fullmatch(r"Exhibit ([A-Z])", stripped):
            current = []
            exhibits.append((m.group(1), current))
        elif re.match(r"\d{1,2}\.", stripped):  # the next numbered agenda section
            current = None
        elif current is not None and stripped:
            current.append(stripped)
    return [(letter, normalize_space(" ".join(lines))) for letter, lines in exhibits if lines]


def meeting_items(meeting: dict, agenda_pdf: bytes) -> list[dict]:
    day = meeting["date"].isoformat()
    return [
        {
            "id": f"library-{day}-{letter}",
            "commission": "library",
            "meeting_date": day,
            "item_number": letter,
            "title": text,
            "text": f"[Board of Library Commissioners, Exhibit {letter}]\n{text}",
            "urls": [meeting["page_url"], *([meeting["exhibits"][letter]] if letter in meeting["exhibits"] else [])],
        }
        for letter, text in split_exhibits(pdf_text(agenda_pdf))
    ]
