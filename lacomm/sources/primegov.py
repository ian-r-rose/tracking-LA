"""PrimeGov meeting portals, starting with the Department of Public Works.

Public Works runs its own portal (separate from City Council's). Board of Public
Works agendas are published as HTML with one block per item, which is much easier
to split than a PDF. The Community Forest Advisory Committee is on the same portal
but only posts PDF agendas, so it isn't covered yet.
"""

import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

PORTAL = "https://dpwlacity.primegov.com"


def commission_slug(title: str) -> str | None:
    if "cancel" in title.lower() or "official notice" in title.lower():
        return None
    if title.startswith("BPW"):
        return "bpw"
    return None  # e.g. council district town halls hosted on the portal


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    raw = []
    for year in range(start.year, end.year + 1):
        resp = client.get(f"{PORTAL}/api/v2/PublicPortal/ListArchivedMeetings", params={"year": year})
        resp.raise_for_status()
        raw += resp.json()
    resp = client.get(f"{PORTAL}/api/v2/PublicPortal/ListUpcomingMeetings")
    resp.raise_for_status()
    raw += resp.json()

    meetings, seen = [], set()
    for m in raw:
        slug = commission_slug(m["title"])
        doc = next((d for d in m["documentList"] if d["templateName"] == "HTML Agenda"), None)
        journal = next((d for d in m["documentList"] if d["templateName"] == "HTML Journal"), None)
        meeting_date = datetime.fromisoformat(m["dateTime"]).date()
        if not slug or not doc or m["id"] in seen or not start <= meeting_date <= end:
            continue
        seen.add(m["id"])
        meetings.append(
            {
                "commission": slug,
                "date": meeting_date,
                # Several BPW meetings can share a date (regular + management), so keep the
                # PrimeGov meeting id to keep item ids unique.
                "meeting_id": m["id"],
                "agenda_url": f"{PORTAL}/Portal/Meeting?compiledMeetingDocumentFileId={doc['id']}",
                "journal_url": f"{PORTAL}/Portal/Meeting?compiledMeetingDocumentFileId={journal['id']}" if journal else None,
            }
        )
    return meetings


def _text(element) -> str:
    text = element.get_text("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{2,}", "\n", "\n".join(line for line in lines if line)).strip()


def meeting_items(meeting: dict, agenda_html: bytes) -> list[dict]:
    soup = BeautifulSoup(agenda_html, "html.parser")
    items = []
    for block in soup.select("div.meeting-item"):
        number_cell = block.select_one("td")
        number = re.search(r"\((\w+)\)", number_cell.get_text()) if number_cell else None
        body = block.select_one("div.agenda-item")
        if not number or not body:
            continue
        text = _text(body)
        section = block.find_parent("div", class_="section-with-items")
        heading = section.select_one("tr.section-row") if section else None
        if heading and (section_name := _text(heading)):
            text = f"[{section_name}]\n{text}"
        urls = [meeting["agenda_url"]] + [
            PORTAL + a["href"]
            for a in block.select("div.attachment-holder a[href*='historyattachment']")
        ]
        matter = re.search(r"[A-Z]{2,5}-\d{4}-\d{3,5}", text)
        items.append(
            {
                "id": f"{meeting['commission']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number.group(1)}",
                "commission": meeting["commission"],
                "meeting_date": meeting["date"].isoformat(),
                "item_number": number.group(1),
                "title": matter.group(0) if matter else text.splitlines()[0],
                "text": text,
                "urls": urls,
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
        count = lambda m: 0 if not m or m.group(1).strip().upper().startswith("NONE") else len(m.group(1).split(","))
        disposition_text = re.sub(r"\s+", " ", disposition.group(1)).strip()
        outcome = {"text": disposition_text, "source": meeting["journal_url"]}
        if ayes:
            outcome["vote"] = f"{count(ayes)}-{count(nays)}"
        outcomes[f"{meeting['commission']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number.group(1)}"] = outcome
    return outcomes
