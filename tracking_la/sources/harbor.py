"""Board of Harbor Commissioners (Port of Los Angeles).

The archive page lists each meeting as a video tile with links to its agendas (regular,
special, revised, committee). Agendas are HTML pages: lettered sections, numbered board
reports ("1. RESOLUTION NO. ___ - APPROVE ...") with Summary and Recommendation text,
followed by links to the board report and its transmittals.
"""

import re
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

ARCHIVE = "https://portoflosangeles.org/commission/agenda-archive-and-videos"
AGENDA_URL = re.compile(r"/agendas/(\d{4})/(\d{8})-([a-z-]+)", re.IGNORECASE)
ITEM_START = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
SECTION = re.compile(r"^[A-Z]\.\s*(\S.*)?$")


def parse_archive(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    meetings, seen = [], set()
    for a in soup.select(".youtube-gallery-item a[href]"):
        m = AGENDA_URL.search(a["href"])
        # Board agendas only; committees (e.g. audit) are separate bodies.
        if not m or "committee" in m.group(3).lower():
            continue
        url = urljoin(ARCHIVE, a["href"]).lower()
        if url in seen:
            continue
        seen.add(url)
        meetings.append(
            {
                "body": "harbor",
                "date": datetime.strptime(m.group(2), "%m%d%Y").date(),
                "kind": m.group(3).lower().replace("-agenda", ""),  # regular, special
                "agenda_url": url,
            }
        )
    return meetings


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(ARCHIVE)
    resp.raise_for_status()
    return [m for m in parse_archive(resp.text) if start <= m["date"] <= end]


def _lines(html: bytes) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    # The agenda body is the smallest container holding both its heading and its end.
    root = soup.find(string=re.compile("ORDER OF BUSINESS"))
    while root is not None and not re.search(r"ADJOURN", root.get_text() if hasattr(root, "get_text") else ""):
        root = root.parent
    root = root or soup
    for a in root.select("a[href]"):
        a.append(f" <{urljoin(ARCHIVE, a['href'])}>")
    lines = [re.sub(r"\s+", " ", line).strip() for line in root.get_text("\n").splitlines()]
    return [line for line in lines if line]


def meeting_items(meeting: dict, agenda_html: bytes) -> list[dict]:
    day = meeting["date"].isoformat()
    items: list[dict] = []
    current = None
    for line in _lines(agenda_html):
        links = re.findall(r"<(https?://[^>]+)>", line)
        if m := ITEM_START.match(line):
            number = f"{meeting['kind']}-{m.group(1)}"
            current = {
                "id": f"harbor-{day}-{number}",
                "body": "harbor",
                "meeting_date": day,
                "item_number": number,
                "title": re.sub(r"^RESOLUTION NO\.?\s*_*\s*-\s*", "", m.group(2))[:200],
                "text": m.group(2),
                "urls": [meeting["agenda_url"]],
            }
            items.append(current)
        elif SECTION.match(line):
            current = None  # e.g. "K." ends the board reports
        elif current is not None:
            current["urls"] += links
            if text := re.sub(r"\s*<https?://[^>]+>", "", line).strip():
                current["text"] += "\n" + text
    return items
