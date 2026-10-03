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

# An item header: "6.     CPC-2026-3542-GPA-ZC   Council District: 7". Usually at the left
# margin, but some agendas indent a few. Requested actions inside an item are indented too,
# but have a single space after the number ("1. Pursuant to ..."), so they don't match.
ITEM_START = re.compile(r"^ {0,5}(\d{1,2}[a-z]?)\. {2,}(\S.*)$")

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


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    meetings = []
    for year in range(start.year, end.year + 1):
        resp = client.get(API.format(year=year))
        resp.raise_for_status()
        for entry in resp.json()["Entries"]:
            slug = commission_slug(entry)
            when = datetime.strptime(entry["Date"], "%m/%d/%Y").date()
            if not slug or not entry["AgendaLink"] or "cancel" in entry["Note"].lower() or not start <= when <= end:
                continue
            meetings.append(
                {"body": slug, "date": when, "agenda_url": entry["AgendaLink"], "minutes_url": entry["MinutesLink"] or None}
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
                "id": f"{meeting['body']}-{meeting_date.isoformat()}-{number}",
                "body": meeting["body"],
                "meeting_date": meeting_date.isoformat(),
                "item_number": number,
                "title": item_title(text),
                "text": text,
                "urls": urls,
            }
        )
    return items


MINUTES_ITEM = re.compile(r"^\s*ITEM NO\.\s*(\d{1,2}[a-z]?)\s*$")
# Procedural first actions (CEQA findings, conditions) say little about the decision itself.
PROCEDURAL = re.compile(r"^(Determine|Find|Adopt|Recommend that the City Council adopt the)", re.IGNORECASE)


def minutes_outcomes(meeting: dict, minutes_text: str) -> dict[str, dict]:
    """Outcomes by item id from meeting minutes. Each "ITEM NO. 5a" block has the motion,
    its numbered actions, a "Vote: 8–0" line and "MOTION PASSED" or "MOTION FAILED"."""
    blocks: dict[str, list[str]] = {}
    current = None
    for line in minutes_text.splitlines():
        if m := MINUTES_ITEM.match(line):
            current = m.group(1)
            blocks[current] = []
        elif current:
            blocks[current].append(line.strip())
    outcomes = {}
    for number, lines in blocks.items():
        text = "\n".join(lines)
        result = re.search(r"MOTION (PASSED|FAILED)", text)
        if not result:
            continue  # standing items with no motion
        # Numbered actions, each joined with its continuation lines.
        actions: list[str] = []
        for l in lines:
            if re.match(r"^\d+\.\s+\S", l):
                actions.append(re.sub(r"^\d+\.\s*", "", l))
            elif actions and l and not re.match(r"^([a-z]\.|Moved:|Second|Ayes|Nays|Absent|Vote|MOTION|Commissioner)", l):
                actions[-1] += " " + l
            elif actions and not l:
                continue
        actions = [re.sub(r"\s+", " ", a) for a in actions]
        action = next((a for a in actions if not PROCEDURAL.match(a)), actions[0] if actions else "")
        if not actions and (moved := re.search(r"moved to ([^.]+)\.", text)):
            action = moved.group(1)  # e.g. "continue the item to August 13, 2026"
        if result.group(1) == "FAILED":
            status = "other"  # a failed motion can lead to a later vote, denial or continuance
        elif re.match(r"(continue|postpone)", action, re.IGNORECASE):
            status = "continued"
        elif re.match(r"(deny|disapprove)", action, re.IGNORECASE):
            status = "denied"  # for appeals, denying the appeal upholds the project
        else:
            status = "approved"
        outcome = {"status": status, "text": f"MOTION {result.group(1)}: {action[:240]}", "source": meeting["minutes_url"]}
        if vote := re.search(r"Vote:\s*(\d+)\s*[–-]\s*(\d+)", text):
            outcome["vote"] = f"{vote.group(1)}-{vote.group(2)}"
        outcomes[f"{meeting['body']}-{meeting['date'].isoformat()}-{number}"] = outcome
    return outcomes
