"""StreetsLA tree removal postings (Urban Forestry Division).

Not a commission, but how proposed street-tree removals are noticed before a Board of
Public Works hearing: one table of currently posted locations. The table is read on
every run (its "meeting" is today) and each posting is an item keyed by posting ID, so
hearing dates added later update the same item.
"""

import re
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

LISTING = "https://permits.streets.lacity.gov/treepostings/public/pending_postings.cfm"


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    today = date.today()
    return [{"body": "trees", "date": today, "agenda_url": f"{LISTING}#{today.isoformat()}"}]


def _date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def meeting_items(meeting: dict, listing_html: bytes) -> list[dict]:
    soup = BeautifulSoup(listing_html, "html.parser")
    rows = soup.find_all("tr")
    if not rows:
        return []
    headers = [th.get_text(" ", strip=True) for th in rows[0].find_all(["th", "td"])]
    items = []
    for row in rows[1:]:
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in row.find_all("td")]
        if len(cells) != len(headers):
            continue
        posting = dict(zip(headers, cells))
        posted, hearing = _date(posting.get("Posting Date", "")), _date(posting.get("Hearing Date", ""))
        if not posted:
            continue
        link = row.find("a", href=True)
        # Drop the session token ColdFusion appends to links.
        detail = re.sub(r"&session\.addtoken$", "", urljoin(LISTING, link["href"])) if link else LISTING
        n, where, why = posting.get("No. of Trees", "?"), posting.get("Address or Location", ""), posting.get("Removal Reason", "")
        text = "\n".join(f"{k}: {v}" for k, v in posting.items() if v)
        items.append(
            {
                "id": f"trees-{posting['Posting ID']}",
                "body": "trees",
                "meeting_date": (hearing or posted).isoformat(),
                "item_number": posting["Posting ID"],
                "title": f"Removal of {n} street trees at {where}: {why}",
                "text": f"[Proposed street tree removal posted by StreetsLA Urban Forestry]\n{text}",
                "urls": [detail],
            }
        )
    return items
