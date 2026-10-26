"""Board of Zoo Commissioners (advisory).

https://lazoo.org/about/zoo-commission/ shows only the next or latest meeting's agenda,
inline as HTML, with linked supporting documents. Each meeting's agenda URL gets its date
as a fragment so a new month's agenda on the same page isn't mistaken for one already fetched.

The General Manager's "Animal Updates" report (animals arriving, leaving, born and died) is a
linked PDF, fetched and made an item of its own.
"""

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from tracking_la import http_client
from tracking_la.pdf import normalize_space, pdf_text

PAGE = "https://lazoo.org/about/zoo-commission/"
CONTEXT = "[Los Angeles Zoo, 5333 Zoo Drive, in Griffith Park]"
# The month is sometimes lowercase ("TUESDAY, october 20, 2026").
MEETING_DATE = re.compile(r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY),\s+([A-Z]+ \d{1,2}, \d{4})", re.I)
STANDING = re.compile(r"^(CALL TO ORDER|APPROVAL OF MINUTES|PUBLIC COMMENT|NEIGHBORHOOD COUNCIL COMMENTS|ADJOURNMENT|.*MEETING$)")
# Agenda headings are all-caps lines, some starting with a year; the agenda ends at adjournment.
HEADING = re.compile(r"^[A-Z0-9][A-Z0-9 .,&’'–/-]{5,}$")
# Under General Manager Reports: "Animal Updates" on one line, its PDF link on the next.
ANIMAL_UPDATES = re.compile(r"^Animal Updates$", re.I)


def _agenda_lines(html: str) -> tuple[date | None, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a[href]"):
        a.append(f" <{a['href']}>")  # keep document links in the text
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    start = next((i for i, line in enumerate(lines) if MEETING_DATE.search(line)), None)
    if start is None:
        return None, []
    when = datetime.strptime(MEETING_DATE.search(lines[start]).group(1).title(), "%B %d, %Y").date()
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("ADJOURNMENT")), len(lines))
    return when, lines[start:end + 1]


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(PAGE)
    resp.raise_for_status()
    when, _ = _agenda_lines(resp.text)
    if not when or not start <= when <= end:
        return []
    return [{"body": "zoo", "date": when, "agenda_url": f"{PAGE}#{when.isoformat()}"}]


def animal_updates_url(lines: list[str]) -> str | None:
    for line, following in zip(lines, lines[1:]):
        if ANIMAL_UPDATES.match(line) and (link := re.fullmatch(r"<(https?://[^>]+)>", following)):
            return link.group(1)
    return None


def meeting_items(meeting: dict, page_html: bytes) -> list[dict]:
    when, lines = _agenda_lines(page_html.decode("utf-8", "replace"))
    if when != meeting["date"]:
        return []  # the page moved on to another meeting
    report = None
    if url := animal_updates_url(lines):
        with http_client(timeout=60) as client:
            resp = client.get(url)
            resp.raise_for_status()
            report = (url, normalize_space(pdf_text(resp.content)))
    return items_from_page(meeting, lines, report)


def items_from_page(meeting: dict, lines: list[str], report: tuple[str, str] | None) -> list[dict]:
    """Agenda sections, plus the Animal Updates report (its URL and text) as an item of its own."""
    sections: list[list[str]] = []
    for line in lines[1:]:
        if HEADING.match(line):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
    items = []
    day = meeting["date"].isoformat()
    for section in sections:
        heading = section[0]
        if STANDING.match(heading):
            continue
        body = "\n".join(section)
        number = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:50]
        items.append(
            {
                "id": f"zoo-{day}-{number}",
                "body": "zoo",
                "meeting_date": day,
                "item_number": number,
                "title": heading.title(),
                "text": f"{CONTEXT}\n{body}",
                "urls": [meeting["agenda_url"], *re.findall(r"<(https?://[^>]+)>", body)],
            }
        )
    if report:
        url, text = report
        items.append(
            {
                "id": f"zoo-{day}-animal-updates",
                "body": "zoo",
                "meeting_date": day,
                "item_number": "animal-updates",
                "title": "Animal Updates",
                "text": f"{CONTEXT}\n{text}",
                "urls": [meeting["agenda_url"], url],
            }
        )
    return items
