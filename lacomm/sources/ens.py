"""Agendas posted to the City's Electronic Notification System (ens.lacity.org).

Several departments post agenda PDFs to a simple listing page there. Each body
formats its agenda differently, so each gets a small `Format` describing how to
split it into items.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin

import httpx

from lacomm.pdf import normalize_space, pdf_links, pdf_text

MONTH_DATE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})")


@dataclass
class Format:
    commission: str
    listing_url: str
    item_start: re.Pattern  # groups: (number, first line)
    skip_item: re.Pattern | None = None  # standing items to drop, matched on the first line
    end_item: re.Pattern | None = None  # lines that end the current item without starting one
    section: re.Pattern | None = None  # section headings, kept as context on the items below them
    ignore_line: re.Pattern | None = None  # page headers, footers, page numbers
    end_agenda: re.Pattern | None = None


TRANSPORTATION = Format(
    commission="transportation",
    listing_url="https://ens.lacity.org/ladot/dotcmA3a.htm",
    item_start=re.compile(r"^\s{0,6}(\d{1,2})\.​?\s*(\S.*)$"),
    skip_item=re.compile(r"Welcome|Roll Call|Approval of Minutes|Commission Business|Communications|General Manager", re.I),
    section=re.compile(r"^([A-Z][A-Z ,&]{4,})$"),
    ignore_line=re.compile(r"^BOARD OF TRANSPORTATION\s*$|COMMISSIONERS AGENDA.*- \d+ -"),
    end_agenda=re.compile(r"^ADJOURNMENT"),
)

RECREATION_AND_PARKS = Format(
    commission="rap",
    listing_url="https://ens.lacity.org/rap/ens_rap_agenda.htm",
    item_start=re.compile(r"^\s{0,3}(\d{2}-\d{3})\s{2,}(\S.*)$"),
    # Numbered agenda sections ("8. COMMISSION TASK FORCE UPDATES") end the board reports.
    end_item=re.compile(r"^\s{0,8}\d{1,2}\.\s+[A-Z]"),
    ignore_line=re.compile(r"^\s+\d{1,2}\s*$"),
)

# Rec & Parks agendas are fetched from Rec & Parks' own site (lacomm.sources.rap), which
# also has minutes and extra documents; RECREATION_AND_PARKS is still the agenda format.
FORMATS = [TRANSPORTATION]


def meeting_date(title: str, href: str) -> date | None:
    """Prefer the date in the link text; filenames carry the posting date, which can differ."""
    if m := MONTH_DATE.search(title):
        return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date()
    if m := re.search(r"_(\d{8})\.pdf$", href):
        return datetime.strptime(m.group(1), "%m%d%Y").date()
    return None


def list_meetings(fmt: Format, start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(fmt.listing_url)
    resp.raise_for_status()
    meetings = []
    for href, title in re.findall(r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>', resp.text, re.S | re.I):
        title = re.sub(r"<[^>]+>|\s+", " ", title).strip()
        when = meeting_date(title, href)
        if not when or not start <= when <= end or "cancel" in title.lower():
            continue
        meetings.append({"commission": fmt.commission, "date": when, "agenda_url": urljoin(fmt.listing_url, href)})
    return meetings


def split_agenda(fmt: Format, text: str) -> list[tuple[str, str, str | None]]:
    """Split agenda text into (item number, item text, section heading)."""
    items: list[tuple[str, list[str], str | None]] = []
    current: list[str] | None = None
    section = None
    for line in text.splitlines():
        if fmt.end_agenda and fmt.end_agenda.match(line.strip()):
            break
        if fmt.ignore_line and fmt.ignore_line.search(line):
            continue
        if m := fmt.item_start.match(line):
            current = [m.group(2)]
            items.append((m.group(1), current, section))
        elif fmt.section and (m := fmt.section.match(line.strip())) and line == line.lstrip():
            section, current = m.group(1).strip(), None
        elif fmt.end_item and fmt.end_item.match(line):
            current = None
        elif current is not None:
            current.append(line)
    return [
        (number, normalize_space("\n".join(lines)), section)
        for number, lines, section in items
        if not (fmt.skip_item and fmt.skip_item.search(lines[0]))
    ]


def items_from_text(fmt: Format, meeting: dict, agenda_text: str, links: list[str]) -> list[dict]:
    items = []
    for number, text, section in split_agenda(fmt, agenda_text):
        # Rec & Parks links each board report by its number, e.g. .../sep17/26-213.pdf
        reports = [u if u.startswith("http") else f"https://{u}" for u in links if u.endswith(f"/{number}.pdf")]
        items.append(
            {
                "id": f"{fmt.commission}-{meeting['date'].isoformat()}-{number}",
                "commission": fmt.commission,
                "meeting_date": meeting["date"].isoformat(),
                "item_number": number,
                "title": text.splitlines()[0],
                "text": f"[{section}]\n{text}" if section else text,
                "urls": [meeting["agenda_url"], *reports],
            }
        )
    return items


def meeting_items(fmt: Format, meeting: dict, agenda_pdf: bytes) -> list[dict]:
    return items_from_text(fmt, meeting, pdf_text(agenda_pdf), pdf_links(agenda_pdf))
