"""PrimeGov meeting portals: the Department of Public Works' here, and the shared
listing and HTML agenda parsing that City Council's portal reuses (lacomm.sources.council).

Public Works runs its own portal (separate from City Council's). Board of Public
Works agendas are published as HTML with one block per item, which is much easier
to split than a PDF. The Community Forest Advisory Committee is on the same portal
but only posts PDF agendas; those are split by their lettered sub-items.
"""

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from lacomm.pdf import normalize_space, pdf_text

PORTAL = "https://dpwlacity.primegov.com"


def commission_slug(title: str) -> str | None:
    if "cancel" in title.lower() or "official notice" in title.lower():
        return None
    if "CFAC" in title or "Community Forest" in title:
        return "cfac"
    if title.startswith("BPW"):
        return "bpw"
    return None  # e.g. council district town halls hosted on the portal


def portal_meetings(portal: str, start: date, end: date, client: httpx.Client) -> list[dict]:
    """Raw meeting records from a PrimeGov portal: archived years in the range, plus upcoming."""
    raw = []
    for year in range(start.year, end.year + 1):
        resp = client.get(f"{portal}/api/v2/PublicPortal/ListArchivedMeetings", params={"year": year})
        resp.raise_for_status()
        raw += resp.json()
    resp = client.get(f"{portal}/api/v2/PublicPortal/ListUpcomingMeetings")
    resp.raise_for_status()
    return raw + resp.json()


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    meetings, seen = [], set()
    for m in portal_meetings(PORTAL, start, end, client):
        slug = commission_slug(m["title"])
        doc = next((d for d in m["documentList"] if d["templateName"] == "HTML Agenda"), None)
        journal = next((d for d in m["documentList"] if d["templateName"] == "HTML Journal"), None)
        pdf = next((d for d in m["documentList"] if d["compileOutputType"] == 1 and "agenda" in d["templateName"].lower()), None)
        meeting_date = datetime.fromisoformat(m["dateTime"]).date()
        if slug == "cfac" and pdf and not doc:
            doc = None  # CFAC: PDF only
        elif not doc:
            continue
        if not slug or m["id"] in seen or not start <= meeting_date <= end:
            continue
        seen.add(m["id"])
        meetings.append(
            {
                "body": slug,
                "date": meeting_date,
                # Several BPW meetings can share a date (regular + management), so keep the
                # PrimeGov meeting id to keep item ids unique.
                "meeting_id": m["id"],
                "portal": PORTAL,
                "agenda_url": (
                    f"{PORTAL}/Portal/Meeting?compiledMeetingDocumentFileId={doc['id']}" if doc
                    else f"{PORTAL}/Public/CompiledDocument?meetingTemplateId={pdf['templateId']}&compileOutputType=1"
                ),
                "journal_url": f"{PORTAL}/Portal/Meeting?compiledMeetingDocumentFileId={journal['id']}" if journal else None,
            }
        )
    return meetings


def _text(element) -> str:
    text = element.get_text("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{2,}", "\n", "\n".join(line for line in lines if line)).strip()


# CFAC sections whose lettered sub-items are substantive (the rest are roll call, minutes, etc.).
CFAC_SECTIONS = re.compile(r"DEPARTMENT|NEW BUSINESS|OLD BUSINESS|REPORT", re.IGNORECASE)


def cfac_items(meeting: dict, agenda_text: str) -> list[dict]:
    day = meeting["date"].isoformat()
    items: list[dict] = []
    section_number = section = None
    current = None
    for line in agenda_text.splitlines():
        if m := re.match(r"^(\d{1,2})\.\s+(\S.*)$", line):
            section_number, section, current = m.group(1), m.group(2), None
        elif section and CFAC_SECTIONS.search(section) and (m := re.match(r"^\s+([A-H])\.\u200b?\s+(\S.*)$", line)):
            number = f"{section_number}{m.group(1)}"
            current = {
                "id": f"cfac-{day}-{number}",
                "body": "cfac",
                "meeting_date": day,
                "item_number": number,
                "title": m.group(2).strip()[:200],
                "text": f"[{section.strip()}]\n{m.group(2).strip()}",
                "urls": [meeting["agenda_url"]],
            }
            items.append(current)
        elif current is not None and line.strip():
            current["text"] += "\n" + line.strip()
    for item in items:
        item["text"] = normalize_space(item["text"])
    return [i for i in items if not re.fullmatch(r"(Other|Recreation & Parks -?)", i["title"].strip())]


def html_items(meeting: dict, agenda_html: bytes) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(item number, text, [(attachment name, URL)]) for each item of a PrimeGov HTML agenda.
    The text starts with the item's section heading in brackets, when it has one."""
    soup = BeautifulSoup(agenda_html, "html.parser")
    items = []
    for block in soup.select("div.meeting-item"):
        # Council's agendas put a paperclip column before the number.
        number_cell = block.select_one("td.number-cell") or block.select_one("td")
        number = re.search(r"\((\w+)\)", number_cell.get_text()) if number_cell else None
        body = block.select_one("div.agenda-item")
        if not number or not body:
            continue
        text = _text(body)
        section = block.find_parent("div", class_="section-with-items")
        heading = section.select_one("tr.section-row") if section else None
        if heading and (section_name := _text(heading)):
            text = f"[{section_name}]\n{text}"
        attachments = [
            (a.get_text(" ", strip=True), meeting.get("portal", PORTAL) + a["href"])
            for a in block.select("div.attachment-holder a[href*='historyattachment']")
        ]
        items.append((number.group(1), text, attachments))
    return items


def meeting_items(meeting: dict, agenda_html: bytes) -> list[dict]:
    if meeting["body"] == "cfac":
        return cfac_items(meeting, pdf_text(agenda_html))
    items = []
    for number, text, attachments in html_items(meeting, agenda_html):
        matter = re.search(r"[A-Z]{2,5}-\d{4}-\d{3,5}", text)
        items.append(
            {
                "id": f"{meeting['body']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number}",
                "body": meeting["body"],
                "meeting_date": meeting["date"].isoformat(),
                "item_number": number,
                "title": matter.group(0) if matter else text.splitlines()[0],
                "text": text,
                "urls": [meeting["agenda_url"], *(url for _, url in attachments)],
            }
        )
    return items


def journal_outcomes(meeting: dict, journal_html: bytes) -> dict[str, dict]:
    """Outcomes by item id from a meeting's HTML Journal, which repeats each agenda item
    with its DISPOSITION and roll call."""
    soup = BeautifulSoup(journal_html, "html.parser")
    outcomes = {}
    for block in soup.select("div.meeting-item"):
        number_cell = block.select_one("td")
        number = re.search(r"\((\w+)\)", number_cell.get_text()) if number_cell else None
        text = block.get_text("\n")
        disposition = re.search(r"DISPOSITION:\s*(.+?)(?=\n\s*(?:MOVED|SECONDED|AYES|[A-Z]{2,5}-\d{4}-\d)|\Z)", text, re.S)
        if not number or not disposition:
            continue
        ayes = re.search(r"AYES:\s*([^;\n]*)", text)
        nays = re.search(r"NAYS:\s*([^;\n]*)", text)
        count = lambda m: 0 if not m else len([n for n in m.group(1).split(",") if n.strip() and n.strip().upper() != "NONE"])
        disposition_text = re.sub(r"\s+", " ", disposition.group(1)).strip()
        outcome = {"text": disposition_text, "source": meeting["journal_url"]}
        if ayes:
            outcome["vote"] = f"{count(ayes)}-{count(nays)}"
        outcomes[f"{meeting['body']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number.group(1)}"] = outcome
    return outcomes
