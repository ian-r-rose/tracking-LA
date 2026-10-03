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
    section: re.Pattern | None = None  # section headings (matched on the raw line), kept as context on the items below them
    ignore_line: re.Pattern | None = None  # page headers, footers, page numbers
    end_agenda: re.Pattern | None = None
    listing_title: re.Pattern | None = None  # only listing links whose text matches
    # Prefix item numbers with their section's number or letter (DWP restarts numbering in
    # each lettered section: N.1, K.1 -> "N1", "K1"; Police letters items in numbered
    # sections: 4.A -> "4A").
    number_with_section: bool = False


TRANSPORTATION = Format(
    commission="transportation",
    listing_url="https://ens.lacity.org/ladot/dotcmA3a.htm",
    item_start=re.compile(r"^\s{0,6}(\d{1,2})\.​?\s*(\S.*)$"),
    skip_item=re.compile(r"Welcome|Roll Call|Approval of Minutes|Commission Business|Communications|General Manager", re.I),
    section=re.compile(r"^([A-Z][A-Z ,&]{4,}?)\s*$"),
    ignore_line=re.compile(r"^BOARD OF TRANSPORTATION\s*$|COMMISSIONERS AGENDA.*- \d+ -"),
    end_agenda=re.compile(r"^ADJOURNMENT"),
)

WATER_AND_POWER = Format(
    commission="dwp",
    listing_url="https://ens.lacity.org/dwp/ens_dwp_agenda.htm",
    listing_title=re.compile(r"Board of Water and Power Commissioners", re.I),
    item_start=re.compile(r"^\s{4,8}(\d{1,2})\.\s+(\S.*)$"),
    skip_item=re.compile(r"approval of the minutes", re.I),
    section=re.compile(r"^([A-Z]\.\s+\S.*?)\s*$"),
    ignore_line=re.compile(r"^\s+\d{1,2}\s*$"),
    end_agenda=re.compile(r"^[A-Z]\.\s+Adjournment"),
    number_with_section=True,
)

BUILDING_AND_SAFETY = Format(
    commission="bbsc",
    listing_url="https://ens.lacity.org/ladbs/ladbs_agenda.htm",
    # Lettered sections (C. PUBLIC NUISANCE HEARINGS, D. PUBLIC HEARINGS regarding
    # EXPORT-IMPORT applications, i.e. haul routes) with items numbered within each.
    item_start=re.compile(r"^\s{4,16}(\d{1,2})\.\s+(\S.*)$"),
    skip_item=re.compile(r"^Election of|^[A-Z][a-z]+ \d{1,2}, \d{4}"),  # officer elections, minutes approvals
    section=re.compile(r"^\s{0,8}([A-Z]\.\s+\S.*?)\s*$"),
    ignore_line=re.compile(r"^AGENDA OF THE\s|^BOARD OF BUILDING AND SAFETY COMMISSIONERS\s{2,}|^LADBS G-5"),  # page headers, footers
    end_agenda=re.compile(r"^[A-Z]\.\s+Public Comments", re.I),
    number_with_section=True,
)

# Police, Fire and Animal Services: numbered sections with lettered items.
POLICE = Format(
    commission="police",
    listing_url="https://ens.lacity.org/lapd/ens_lapd_agenda.htm",
    item_start=re.compile(r"^\s{6,10}([A-Z])\.\s+(\S.*)$"),
    section=re.compile(r"^(\d{1,2}\.\s+\S.*?)\s*$"),
    end_agenda=re.compile(r"^\d{1,2}\.\s+CLOSED SESSION"),  # personnel and litigation, not public decisions
    number_with_section=True,
)

FIRE = Format(
    commission="fire",
    listing_url="https://ens.lacity.org/lafd/ens_lafd_agenda.htm",
    listing_title=re.compile(r"Agenda", re.I),  # not the yearly meeting schedule
    item_start=re.compile(r"^\s{4,8}([A-Z])\.\s+(\S.*)$"),
    skip_item=re.compile(r"^Announcements|^Oral report", re.I),
    section=re.compile(r"^\s{0,3}(\d{1,2}\.\s+\S.*?)\s*$"),
    ignore_line=re.compile(r"EQUAL EMPLOYMENT OPPORTUNITY EMPLOYER|^\s*www\.lafd\.org|^Board of Fire Commission\s{3,}"),
    end_agenda=re.compile(r"^ADJOURNMENT"),
    number_with_section=True,
)

ANIMAL_SERVICES = Format(
    commission="animal",
    listing_url="https://ens.lacity.org/animal/ens_animal_agenda.htm",
    item_start=re.compile(r"^\s{6,10}([A-Z])\.\s+(\S.*)$"),
    skip_item=re.compile(r"^Approval of (the )?Minutes", re.I),
    section=re.compile(r"^\s{2,5}(\d{1,2}\.\s+\S.*?)\s*$"),
    ignore_line=re.compile(r"Please join us at our website|^Board of Animal Services Commissioners Meeting\s*$|^Meeting Agenda \w+ \d|^Page \d+\s*$"),
    end_agenda=re.compile(r"^ADJOURNMENT"),
    number_with_section=True,
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
FORMATS = [TRANSPORTATION, WATER_AND_POWER, BUILDING_AND_SAFETY, POLICE, FIRE, ANIMAL_SERVICES]


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
    listed, cancelled = [], set()
    for href, title in re.findall(r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>', resp.text, re.S | re.I):
        title = re.sub(r"<[^>]+>|\s+", " ", title).strip()
        if fmt.listing_title and not fmt.listing_title.search(title):
            continue
        when = meeting_date(title, href)
        if not when or not start <= when <= end:
            continue
        # A cancellation notice can sit beside the agenda it cancels; drop both. A
        # "Cancellations & Additions" notice (Building and Safety) amends an agenda instead.
        if "cancel" in title.lower():
            if "addition" not in title.lower():
                cancelled.add(when)
            continue
        listed.append({"commission": fmt.commission, "date": when, "agenda_url": urljoin(fmt.listing_url, href)})
    return [m for m in listed if m["date"] not in cancelled]


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
            number = (re.match(r"\w+", section).group() if fmt.number_with_section and section else "") + m.group(1)
            items.append((number, current, section))
        elif fmt.section and (m := fmt.section.match(line)):
            section, current = re.sub(r"\s+", " ", m.group(1)).strip(), None
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
                # DWP items open with "Recommended by <office>"; the substance is on the next line.
                "title": next((l.strip() for l in text.splitlines() if not l.strip().startswith("Recommended by")), number),
                "text": f"[{section}]\n{text}" if section else text,
                "urls": [meeting["agenda_url"], *reports],
            }
        )
    return items


def meeting_items(fmt: Format, meeting: dict, agenda_pdf: bytes) -> list[dict]:
    return items_from_text(fmt, meeting, pdf_text(agenda_pdf), pdf_links(agenda_pdf))
