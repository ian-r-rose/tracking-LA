"""Board of Zoo Commissioners (advisory).

Agendas come from ens.lacity.org, which keeps past ones too. The General Manager's
"Animal Updates" report (animals arriving, leaving, born and died) becomes an item of its
own. It's only on lazoo.org, linked from the Zoo Commission page, whose firewall refuses
scripts; the site's WordPress media listing isn't behind it, so the report is found there:
the newest "Animal Transaction" PDF uploaded in the weeks before the meeting (file names
vary month to month, and a corrected report is uploaded again with "-1" added).

When the report isn't up yet or lazoo.org refuses, the agenda items are still fetched, and
the report is tried again on later fetches until it comes through.
"""

import re
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from tracking_la import http_client
from tracking_la.pdf import normalize_space, pdf_text
from tracking_la.sources import ens
from tracking_la.store import DATA, item_path

LISTING = ens.Format(body="zoo", listing_url="https://ens.lacity.org/zoo/ens_zoo_agenda.htm", item_start=re.compile(""))
MEDIA = "https://lazoo.org/wp-json/wp/v2/media"
# A meeting's report is uploaded about a week before it (sometimes revised the day before).
REPORT_UPLOADED = (timedelta(days=21), timedelta(days=3))  # before, after the meeting
REPORT_FILE = re.compile(r"Animal-Transaction", re.I)
CONTEXT = "[Los Angeles Zoo, 5333 Zoo Drive, in Griffith Park]"

# The agenda PDF has a sidebar (address, commissioners) left of the agenda; the agenda
# column starts where "1. CALL TO ORDER" does.
FIRST_ITEM = re.compile(r"^(.*?\s)1\.\s+CALL TO ORDER")
ITEM = re.compile(r"^\s{0,3}(\d{1,2})\.\s+(\S.*)$")
STANDING = re.compile(r"^(CALL TO ORDER|APPROVAL OF MINUTES|PUBLIC COMMENT|ADJOURNMENT)")


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


def animal_updates_url(media: list[dict], when: date) -> str | None:
    """The Animal Updates report for the meeting on `when`, from lazoo.org's media listing:
    the newest upload of a transaction report around the meeting."""
    uploads = [
        (datetime.fromisoformat(m["date"]), m["source_url"]) for m in media
        if REPORT_FILE.search(m["source_url"]) and m["source_url"].lower().endswith(".pdf")
    ]
    near = [(at, url) for at, url in uploads if when - REPORT_UPLOADED[0] <= at.date() <= when + REPORT_UPLOADED[1]]
    return max(near)[1] if near else None


def report_uploads(when: date, client: httpx.Client) -> list[dict]:
    resp = client.get(MEDIA, params={
        "search": "transaction",
        "after": (when - REPORT_UPLOADED[0]).isoformat() + "T00:00:00",
        "before": (when + REPORT_UPLOADED[1] + timedelta(days=1)).isoformat() + "T00:00:00",
        "per_page": 100,
        "_fields": "date,source_url",
    })
    resp.raise_for_status()
    return resp.json()


def meeting_items(meeting: dict, agenda_pdf: bytes) -> list[dict]:
    text = pdf_text(agenda_pdf)
    items = agenda_items(meeting, text)
    if not re.search(r"Animal Updates", text, re.I):
        return items
    try:
        with http_client(timeout=60) as client:
            if url := animal_updates_url(report_uploads(meeting["date"], client), meeting["date"]):
                resp = client.get(url)
                resp.raise_for_status()
                items.append(animal_updates_item(meeting, url, normalize_space(pdf_text(resp.content))))
            else:
                print(f"  pending: zoo Animal Updates for {meeting['date']} isn't on lazoo.org yet, tried again next fetch")
    except httpx.HTTPError as e:
        print(f"  pending: zoo Animal Updates for {meeting['date']}, tried again next fetch ({e})")
    return items
