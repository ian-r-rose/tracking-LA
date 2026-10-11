"""City Council and its committees, from the City Clerk's PrimeGov portal.

Committees are where Council matters are discussed before going to full Council; a
committee's action is a recommendation to Council.

Full Council passes nearly everything in batches, a section per roll call, unless an
item is called "special"; there's no consent marker on an item. Its agendas skip
closed sessions, nuisance-abatement liens (the -0160-S series of Council Files) and
motions funding a district's events and recognitions. An item whose Council File was
on a watched committee's agenda `follows` that committee item: it carries over the
committee item's extraction instead of being extracted again, and isn't followed for
a decision itself, since the committee item records Council's action. Agendas use the same PrimeGov HTML
as Public Works (tracking_la.sources.primegov). Committees are selected by PrimeGov's
committee id, because their names change (Housing and Homelessness split in two in
2026; Arts and Parks has been renamed twice).

Each item belongs to a Council File, the City's id for a matter as it moves between
committees and Council. Decisions come from the file's page in Clerk Connect
(https://cityclerk.lacity.org/lacityclerkconnect/), whose File Activities record
every step, including what full Council did after the committee, and whose Council
Vote Information has roll calls by member.
"""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from tracking_la.outcomes import normalize_status
from tracking_la.sources import primegov
from tracking_la.store import DATA

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
    49: "council-environment",  # Energy and Environment
    1: "council",  # full City Council
}

# Full Council has met with a regular agenda plus supplemental, special or continuation
# ones; only a few days back, since what it did comes from Clerk Connect, not agendas.
COUNCIL_LOOKBACK = timedelta(days=3)

SKIP_COUNCIL_ITEM = re.compile(
    r"may recess to Closed Session"
    r"|relative to funding for (services in connection with|.*\b(celebration|recognition|observation|commemoration)\b)",
    re.I,
)
LIEN_FILE = re.compile(r"^\d{2}-0160-S\d+$")  # nuisance-abatement liens

# A meeting's HTML agenda, by the name PrimeGov gives its template; a revision replaces the original.
AGENDA_TEMPLATES = ("HTML Revised Special Agenda", "HTML Revised Agenda", "HTML Agenda", "HTML Special Agenda")
COUNCIL_EXTRA_AGENDAS = ("Supplemental", "Special", "Continuation")

COUNCIL_FILE = re.compile(r"^\d{2}-\d{4}(-S\d+)?$")
# Of an item's attachments (the whole Council File's documents, often dozens), link these.
KEY_DOCUMENT = re.compile(r"^(Report|Motion|Resolution|Draft Ordinance|Attachment to Report)", re.I)
MAX_DOCUMENTS = 5


def council_file_url(number: str) -> str:
    return CLERK_CONNECT.format(number)


def agenda_documents(m: dict, body: str) -> list[tuple[str | None, dict]]:
    """(kind, document) for a meeting's HTML agendas: one, plus full Council's extra ones."""
    templates = {d["templateName"].strip(): d for d in m["documentList"]}
    main = next((templates[t] for t in AGENDA_TEMPLATES if t in templates), None)
    documents = [(None, main)] if main else []
    if body == "council":
        for kind in COUNCIL_EXTRA_AGENDAS:
            doc = templates.get(f"HTML Revised {kind} Agenda") or templates.get(f"HTML {kind} Agenda")
            if doc and doc is not main:
                documents.append((kind.lower(), doc))
    return documents


def parse_meetings(raw: list[dict]) -> list[dict]:
    meetings, seen = [], set()
    for m in raw:
        body = COMMITTEES.get(m.get("committeeId"))
        title = m["title"].upper()
        # "SAP" meetings are the Spanish-language duplicates of each agenda.
        if not body or "CANCEL" in title or re.search(r"\bSAP\b", title) or m["id"] in seen:
            continue
        seen.add(m["id"])
        for kind, doc in agenda_documents(m, body):
            meetings.append(
                {
                    "body": body,
                    "date": datetime.fromisoformat(m["dateTime"]).date(),
                    "meeting_id": f"{m['id']}-{kind}" if kind else m["id"],
                    "portal": PORTAL,
                    "agenda_url": f"{PORTAL}/Portal/Meeting?compiledMeetingDocumentFileId={doc['id']}",
                }
            )
    return meetings


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    council_start = max(start, date.today() - COUNCIL_LOOKBACK)
    return [
        m for m in parse_meetings(primegov.portal_meetings(PORTAL, start, end, client))
        if (council_start if m["body"] == "council" else start) <= m["date"] <= end
    ]


def _short(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "…"


def committee_items(root: Path = DATA) -> dict[str, list[tuple[str, str]]]:
    """(meeting date, item id) of watched committees' items, by Council File."""
    found = {}
    for path in (root / "items").glob("council-*/*/*.json"):
        item = json.loads(path.read_text())
        if m := re.match(r"\[Council File ([^;\]]+)", item["text"]):
            found.setdefault(m.group(1), []).append((item["meeting_date"], item["id"]))
    return found


def meeting_items(meeting: dict, agenda_html: bytes, root: Path = DATA) -> list[dict]:
    council = meeting["body"] == "council"
    followed = committee_items(root) if council else {}
    items = []
    for number, text, attachments in primegov.html_items(meeting, agenda_html):
        lines = [l for l in text.splitlines() if not re.fullmatch(r"-+", l)]  # stands in for a missing Council File
        section = lines.pop(0) if lines and lines[0].startswith("[") else None
        if section == "[ITEM(S)]":  # the heading of most committee agendas' only section
            section = None
        council_file = lines.pop(0) if lines and COUNCIL_FILE.match(lines[0]) else None
        district = lines.pop(0) if lines and re.fullmatch(r"CDs? [\d, ]+", lines[0]) else None
        if council and (SKIP_COUNCIL_ITEM.search(lines[0] if lines else text) or LIEN_FILE.match(council_file or "")):
            continue
        header = "; ".join(p for p in (f"Council File {council_file}" if council_file else None, district) if p)
        documents = [url for name, url in attachments if KEY_DOCUMENT.match(name)][:MAX_DOCUMENTS]
        item = {
            "id": f"{meeting['body']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number}",
            "body": meeting["body"],
            "meeting_date": meeting["date"].isoformat(),
            "item_number": number,
            "title": _short(lines[0] if lines else text),
            "text": "\n".join(p for p in (f"[{header}]" if header else None, section, *lines) if p),
            "urls": [meeting["agenda_url"], *([council_file_url(council_file)] if council_file else []), *documents],
        }
        earlier = [c for c in followed.get(council_file, []) if c[0] <= item["meeting_date"]]
        if earlier:
            item["follows"] = max(earlier)[1]
        items.append(item)
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
    if item.get("follows"):  # the committee item it follows records Council's action
        return None
    return next((u for u in item["urls"] if u.startswith(CLERK_CONNECT.split("?")[0])), None)
