"""City Planning Commission, Area Planning Commissions, and Cultural Heritage Commission.

All three publish through the Planning Department's meetings API, the same one
that backs https://planning.lacity.gov/about/commissions-boards-hearings.
"""

import re
from datetime import date, datetime

import httpx

from lacomm.pdf import normalize_space, pdf_links, pdf_text

API = "https://planning.lacity.gov/dcpapi2/meetings/api/all/commissions/{year}"

APC_SLUGS = {
    "Central": "apc-central",
    "East Los Angeles": "apc-east-la",
    "Harbor": "apc-harbor",
    "North Valley": "apc-north-valley",
    "South Los Angeles": "apc-south-la",
    "South Valley": "apc-south-valley",
    "West Los Angeles": "apc-west-la",
}

# Standing agenda items that are the same at every meeting.
BOILERPLATE = re.compile(
    r"DIRECTOR|COMMISSION BUSINESS|NEIGHBORHOOD COUNCIL|PUBLIC COMMENT|"
    r"RECONSIDERATION|CONSENT CALENDAR|ADJOURN",
    re.IGNORECASE,
)

# An item header starts at the left margin: "6.     CPC-2026-3542-GPA-ZC   Council District: 7".
# Requested actions inside an item ("1.  Pursuant to ...") are indented, so they don't match.
ITEM_START = re.compile(r"^(\d{1,2}[a-z]?)\.\s{2,}(\S.*)$")

# Text after the last item: next-meeting notice and legal boilerplate.
AGENDA_END = re.compile(r"^\s*(The next regular meeting of|Notice to Paid Representatives|ADJOURNMENT)")

# Running page header/footer, e.g. "City Planning Commission      3      September 10, 2026".
PAGE_HEADER = re.compile(r"^\s*\S.*Commission\s{2,}\d+\s{2,}[A-Z][a-z]+ \d{1,2}, \d{4}\s*$")


def commission_slug(entry: dict) -> str | None:
    kind, area = entry["Type"], entry["APC"]
    if kind == "City Planning Commission" and area == "Citywide":
        return "cpc"
    if kind == "Cultural Heritage Commission":
        return "chc"
    if kind == "Area Planning Commission":
        return APC_SLUGS.get(area)
    return None  # e.g. hearing officer meetings listed under CPC


def list_meetings(year: int, client: httpx.Client) -> list[dict]:
    resp = client.get(API.format(year=year))
    resp.raise_for_status()
    meetings = []
    for entry in resp.json()["Entries"]:
        slug = commission_slug(entry)
        if not slug or not entry["AgendaLink"] or "cancel" in entry["Note"].lower():
            continue
        meetings.append(
            {
                "commission": slug,
                "date": datetime.strptime(entry["Date"], "%m/%d/%Y").date(),
                "agenda_url": entry["AgendaLink"],
            }
        )
    return meetings


def split_agenda(text: str) -> list[tuple[str, str]]:
    """Split agenda text into (item number, item text), skipping standing boilerplate items."""
    items: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if AGENDA_END.search(line):
            break
        if PAGE_HEADER.match(line):
            continue
        if m := ITEM_START.match(line):
            items.append((m.group(1), [m.group(2)]))
        elif items:
            items[-1][1].append(line)
    return [
        (number, normalize_space("\n".join(lines)))
        for number, lines in items
        if not BOILERPLATE.search(lines[0])
    ]


def case_number(text: str) -> str | None:
    m = re.match(r"([A-Z]{2,5}-\d{4}-\d+)", text)
    return m.group(1) if m else None


def item_title(text: str) -> str:
    """First line of the item, minus the right-hand column (council district etc.)."""
    return re.split(r"\s{2,}", text.splitlines()[0])[0]


def meeting_items(meeting: dict, agenda_pdf: bytes) -> list[dict]:
    return items_from_text(meeting, pdf_text(agenda_pdf), pdf_links(agenda_pdf))


def items_from_text(meeting: dict, agenda_text: str, links: list[str]) -> list[dict]:
    meeting_date: date = meeting["date"]
    items = []
    for number, text in split_agenda(agenda_text):
        urls = [meeting["agenda_url"]]
        if case := case_number(text):
            # Staff report links embed the case number, e.g. .../CPC_2026_3542.pdf
            urls += [u for u in links if case.replace("-", "_") in u]
        items.append(
            {
                "id": f"{meeting['commission']}-{meeting_date.isoformat()}-{number}",
                "commission": meeting["commission"],
                "meeting_date": meeting_date.isoformat(),
                "item_number": number,
                "title": item_title(text),
                "text": text,
                "urls": urls,
            }
        )
    return items
