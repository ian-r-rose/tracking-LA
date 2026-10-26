"""Board of Zoo Commissioners (advisory).

Agendas come from ens.lacity.org, which keeps past ones too. The Zoo's own page,
https://lazoo.org/about/zoo-commission/, shows only the next or latest meeting's agenda, but
it links the supporting documents, including the General Manager's "Animal Updates" report
(animals arriving, leaving, born and died), which becomes an item of its own.

lazoo.org's firewall refuses GitHub's runners on some days. Then the agenda items are still
fetched, and the report is tried again on later fetches until it comes through.
"""

import re
from datetime import date, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from tracking_la import http_client
from tracking_la.pdf import normalize_space, pdf_text
from tracking_la.sources import ens
from tracking_la.store import DATA, item_path

LISTING = ens.Format(body="zoo", listing_url="https://ens.lacity.org/zoo/ens_zoo_agenda.htm", item_start=re.compile(""))
PAGE = "https://lazoo.org/about/zoo-commission/"
CONTEXT = "[Los Angeles Zoo, 5333 Zoo Drive, in Griffith Park]"

# The agenda PDF has a sidebar (address, commissioners) left of the agenda; the agenda
# column starts where "1. CALL TO ORDER" does.
FIRST_ITEM = re.compile(r"^(.*?\s)1\.\s+CALL TO ORDER")
ITEM = re.compile(r"^\s{0,3}(\d{1,2})\.\s+(\S.*)$")
STANDING = re.compile(r"^(CALL TO ORDER|APPROVAL OF MINUTES|PUBLIC COMMENT|ADJOURNMENT)")

# On the Zoo's page. The month is sometimes lowercase ("TUESDAY, october 20, 2026").
MEETING_DATE = re.compile(r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY),\s+([A-Z]+ \d{1,2}, \d{4})", re.I)
# Under General Manager Reports: "Animal Updates" on one line, its PDF link on the next.
ANIMAL_UPDATES = re.compile(r"^Animal Updates$", re.I)


def list_meetings(start: date, end: date, client: httpx.Client, root: Path = DATA) -> list[dict]:
    meetings = ens.list_meetings(LISTING, start, end, client)
    for m in meetings:
        if not item_path(animal_updates_item(m, "", ""), root).exists():
            m["refetch"] = True  # until its Animal Updates report comes through
    return meetings


def agenda_items(meeting: dict, agenda_text: str) -> list[dict]:
    lines = agenda_text.splitlines()
    start = next((i for i, line in enumerate(lines) if FIRST_ITEM.match(line)), None)
    if start is None:
        return []
    column = len(FIRST_ITEM.match(lines[start]).group(1))
    sections: list[list[str]] = []
    for line in lines[start:]:
        line = line[column:]
        if m := ITEM.match(line):
            if m.group(2).startswith("ADJOURNMENT"):
                break
            sections.append([m.group(2).strip()])
        elif sections:
            sections[-1].append(line)
    items = []
    day = meeting["date"].isoformat()
    for heading, *body in sections:
        if STANDING.match(heading):
            continue
        number = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:50]
        items.append(
            {
                "id": f"zoo-{day}-{number}",
                "body": "zoo",
                "meeting_date": day,
                "item_number": number,
                "title": heading.title(),
                "text": normalize_space("\n".join([CONTEXT, heading, *body])),
                "urls": [meeting["agenda_url"]],
            }
        )
    return items


def animal_updates_item(meeting: dict, url: str, text: str) -> dict:
    day = meeting["date"].isoformat()
    return {
        "id": f"zoo-{day}-animal-updates",
        "body": "zoo",
        "meeting_date": day,
        "item_number": "animal-updates",
        "title": "Animal Updates",
        "text": f"{CONTEXT}\n{text}",
        "urls": [meeting["agenda_url"], url],
    }


def _page_lines(html: str) -> tuple[date | None, list[str]]:
    """The Zoo page's meeting date and agenda lines, with document links kept as <url>."""
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a[href]"):
        a.append(f" <{a['href']}>")
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    start = next((i for i, line in enumerate(lines) if MEETING_DATE.search(line)), None)
    if start is None:
        return None, []
    when = datetime.strptime(MEETING_DATE.search(lines[start]).group(1).title(), "%B %d, %Y").date()
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("ADJOURNMENT")), len(lines))
    return when, lines[start:end + 1]


def animal_updates_url(page_html: str, when: date) -> str | None:
    """The Animal Updates report's URL, if the Zoo page still shows the meeting on `when`."""
    page_when, lines = _page_lines(page_html)
    if page_when != when:
        return None
    for line, following in zip(lines, lines[1:]):
        if ANIMAL_UPDATES.match(line) and (link := re.fullmatch(r"<(https?://[^>]+)>", following)):
            return link.group(1)
    return None


def meeting_items(meeting: dict, agenda_pdf: bytes) -> list[dict]:
    text = pdf_text(agenda_pdf)
    items = agenda_items(meeting, text)
    if not re.search(r"Animal Updates", text, re.I):
        return items
    try:
        with http_client(timeout=60) as client:
            resp = client.get(PAGE)
            resp.raise_for_status()
            if url := animal_updates_url(resp.text, meeting["date"]):
                resp = client.get(url)
                resp.raise_for_status()
                items.append(animal_updates_item(meeting, url, normalize_space(pdf_text(resp.content))))
    except httpx.HTTPError as e:
        print(f"  pending: zoo Animal Updates for {meeting['date']}, tried again next fetch ({e})")
    return items
