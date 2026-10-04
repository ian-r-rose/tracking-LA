"""City Council committees, from the City Clerk's PrimeGov portal.

Committees are where Council matters are discussed before going to full Council; a
committee's action is a recommendation to Council. Agendas use the same PrimeGov HTML
as Public Works (lacomm.sources.primegov). Committees are selected by PrimeGov's
committee id, because their names change (Housing and Homelessness split in two in
2026; Arts and Parks has been renamed twice).

Each item belongs to a Council File, the City's id for a matter as it moves between
committees and Council. Decisions come from the file's page in Clerk Connect
(https://cityclerk.lacity.org/lacityclerkconnect/), whose File Activities record
every step, including what full Council did after the committee, and whose Council
Vote Information has roll calls by member.
"""

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from lacomm.outcomes import normalize_status
from lacomm.sources import primegov

PORTAL = "https://lacity.primegov.com"
CLERK_CONNECT = "https://cityclerk.lacity.org/lacityclerkconnect/index.cfm?fa=ccfi.viewrecord&cfnumber={}"

COMMITTEES = {
    12: "council-plum",  # Planning and Land Use Management
    17: "council-transportation",
    108: "council-arts-parks",  # Arts, Parks, Libraries, and Community Enrichment
    119: "council-arts-parks",  # Arts, Parks, and City Facilities (renamed Oct 2026)
    36: "council-public-works",
    104: "council-housing",  # Housing and Homelessness, until it split in 2026
    2: "council-housing",
    121: "council-homelessness",  # Homelessness and Health
}

COUNCIL_FILE = re.compile(r"^\d{2}-\d{4}(-S\d+)?$")
# Of an item's attachments (the whole Council File's documents, often dozens), link these.
KEY_DOCUMENT = re.compile(r"^(Report|Motion|Resolution|Draft Ordinance|Attachment to Report)", re.I)
MAX_DOCUMENTS = 5


def council_file_url(number: str) -> str:
    return CLERK_CONNECT.format(number)


def parse_meetings(raw: list[dict]) -> list[dict]:
    meetings, seen = [], set()
    for m in raw:
        body = COMMITTEES.get(m.get("committeeId"))
        title = m["title"].upper()
        # "SAP" meetings are the Spanish-language duplicates of each agenda.
        if not body or "CANCEL" in title or re.search(r"\bSAP\b", title) or m["id"] in seen:
            continue
        doc = next((d for d in m["documentList"] if d["templateName"] in ("HTML Agenda", "HTML Special Agenda")), None)
        if not doc:
            continue
        seen.add(m["id"])
        meetings.append(
            {
                "body": body,
                "date": datetime.fromisoformat(m["dateTime"]).date(),
                "meeting_id": m["id"],
                "portal": PORTAL,
                "agenda_url": f"{PORTAL}/Portal/Meeting?compiledMeetingDocumentFileId={doc['id']}",
            }
        )
    return meetings


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    return [m for m in parse_meetings(primegov.portal_meetings(PORTAL, start, end, client)) if start <= m["date"] <= end]


def _short(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "…"


def meeting_items(meeting: dict, agenda_html: bytes) -> list[dict]:
    items = []
    for number, text, attachments in primegov.html_items(meeting, agenda_html):
        lines = text.splitlines()
        section = lines.pop(0) if lines and lines[0].startswith("[") else None
        if section == "[ITEM(S)]":  # the heading of most committee agendas' only section
            section = None
        council_file = lines.pop(0) if lines and COUNCIL_FILE.match(lines[0]) else None
        district = lines.pop(0) if lines and re.fullmatch(r"CD \d{1,2}", lines[0]) else None
        header = "; ".join(p for p in (f"Council File {council_file}" if council_file else None, district) if p)
        documents = [url for name, url in attachments if KEY_DOCUMENT.match(name)][:MAX_DOCUMENTS]
        items.append(
            {
                "id": f"{meeting['body']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number}",
                "body": meeting["body"],
                "meeting_date": meeting["date"].isoformat(),
                "item_number": number,
                "title": _short(lines[0] if lines else text),
                "text": "\n".join(p for p in (f"[{header}]" if header else None, section, *lines) if p),
                "urls": [meeting["agenda_url"], *([council_file_url(council_file)] if council_file else []), *documents],
            }
        )
    return items


# File Activities that record a decision (most record scheduling, referrals, documents
# received or transmittals instead).
ACTION = re.compile(
    r"\b(adopted|approved|continued|denied|disapproved|noted and filed|received and filed|granted|"
    r"concurred|withdrawn|vetoed|failed|signed|tabled)\b",
    re.I,
)


def file_activities(soup: BeautifulSoup) -> list[tuple[date, str]]:
    """(date, activity) from a Clerk Connect page's File Activities table, newest first."""
    activities = []
    for row in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
        if len(cells) >= 2 and re.fullmatch(r"\d\d/\d\d/\d{4}", cells[0]) and cells[1]:
            activities.append((datetime.strptime(cells[0], "%m/%d/%Y").date(), re.sub(r"\s+", " ", cells[1]).strip()))
    return activities


def council_votes(text: str) -> dict[date, str]:
    """Council roll-call tallies by meeting date, e.g. {2025-12-12: "14-1-0"}."""
    votes = {}
    for when, tally in re.findall(r"Meeting Date:\s*(\d\d/\d\d/\d{4}).*?Vote Given:\s*\((\d+\s*-\s*\d+\s*-\s*\d+)\)", text, re.S):
        votes.setdefault(datetime.strptime(when, "%m/%d/%Y").date(), re.sub(r"\s", "", tally))
    return votes


def council_file_outcome(html: str, url: str, since: date | None = None) -> dict | None:
    """The latest action on a Council File (by a committee or by Council) since `since`, the
    item's meeting date: a Council File can have been decided before, on an earlier motion.
    When Council acted on a committee's report, the committee's action comes first, since
    "Council adopted item" alone doesn't say what the committee recommended (e.g. whether
    PLUM granted or denied an appeal)."""
    soup = BeautifulSoup(html, "html.parser")
    activities = [(when, text.rstrip(" .")) for when, text in file_activities(soup) if not since or when >= since]
    actions = [(when, text) for when, text in activities if ACTION.search(text) and "transmitted" not in text.lower()]
    if not actions:
        return None
    when, text = max(actions, key=lambda a: a[0])  # File Activities are newest first; max keeps the first on a tie
    text = f"{text} ({when:%b %-d, %Y})"
    if text.startswith("Council ") and (
        committee := next(((w, t) for w, t in actions if w <= when and "Committee" in t), None)
    ):
        text = f"{committee[1]} ({committee[0]:%b %-d, %Y}); {text}"
    if any(w >= when and "Council action final" in t for w, t in activities):
        text += "; Council action final"  # past the Mayor's and Council's reconsideration windows
    outcome = {"status": normalize_status(text), "text": text, "source": url}
    if when in (votes := council_votes(soup.get_text(" "))):
        outcome["vote"] = votes[when]
    return outcome


def follow_url(item: dict) -> str | None:
    return next((u for u in item["urls"] if u.startswith(CLERK_CONNECT.split("?")[0])), None)
