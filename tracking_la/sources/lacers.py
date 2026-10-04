"""LACERS Board of Administration (Los Angeles City Employees' Retirement System).

lacers.org lists each meeting's agenda as one "combined" PDF: the agenda followed by
every staff report. Only the agenda pages are read; they use Roman-numeral sections
with lettered items, which the ENS agenda splitter handles.
"""

import re
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from tracking_la.pdf import pdf_text
from tracking_la.sources.ens import Format, items_from_text

PAGE = "https://www.lacers.org/agendas-and-minutes"
TITLE = re.compile(r"^(\w+ \d{1,2}, \d{4}) - Board of Administration Meeting Agenda$")
AGENDA_PAGES = 12  # the agenda itself is a few pages; staff reports follow

FORMAT = Format(
    body="lacers",
    listing_url=PAGE,
    item_start=re.compile(r"^\s{4,12}([A-Z])\.\s+(\S.*)$"),
    skip_item=re.compile(r"VERBAL REPORT|APPROVAL OF MINUTES|CLOSED SESSION|REPORT ON DEPARTMENT OPERATIONS|UPCOMING AGENDA ITEMS"),
    section=re.compile(r"^\s{0,4}([IVX]+\.\s+\S.*?)\s*$"),
    end_agenda=re.compile(r"^[IVX]+\.\s+ADJOURNMENT"),
    number_with_section=True,
)


def parse_page(html: str) -> list[dict]:
    meetings = []
    for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        if m := TITLE.match(a.get_text(" ", strip=True)):
            meetings.append(
                {
                    "body": "lacers",
                    "date": datetime.strptime(m.group(1), "%B %d, %Y").date(),
                    # The query string is a cache-buster that changes when the file is re-uploaded.
                    "agenda_url": urljoin(PAGE, a["href"]).split("?")[0],
                }
            )
    return meetings


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    meetings = []
    for page in range(4):  # newest first, about two months per page
        resp = client.get(PAGE, params={"page": page} if page else None)
        resp.raise_for_status()
        found = parse_page(resp.text)
        meetings += [m for m in found if start <= m["date"] <= end]
        if not found or min(m["date"] for m in found) < start:
            break
    return meetings


def meeting_items(meeting: dict, packet_pdf: bytes) -> list[dict]:
    return items_from_text(FORMAT, meeting, pdf_text(packet_pdf, last_page=AGENDA_PAGES), [])
