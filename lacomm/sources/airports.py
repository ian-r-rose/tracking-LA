"""Board of Airport Commissioners (Los Angeles World Airports: LAX and Van Nuys).

Meetings come from LAWA's Granicus RSS feed of agendas; each agenda is HTML that
Granicus generates, with numbered items (`td.numberspace`) under Roman-numeral sections
and staff report links (MetaViewer) after each item.
"""

import re
from datetime import date
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

FEED = "https://lawa.granicus.com/ViewPublisherRSS.php?view_id=4&mode=agendas"


def parse_feed(xml: str) -> list[dict]:
    meetings = []
    for item in ElementTree.fromstring(xml).iter("item"):
        title = item.findtext("title", "")
        # Board meetings only; committees (e.g. "Security Committee Meeting") are separate bodies.
        if "committee" in title.lower() or "cancel" in title.lower():
            continue
        meetings.append(
            {
                "commission": "airports",
                "date": parsedate_to_datetime(item.findtext("pubDate")).date(),
                "agenda_url": item.findtext("link").strip(),
            }
        )
    return meetings


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(FEED)
    resp.raise_for_status()
    return [m for m in parse_feed(resp.text) if start <= m["date"] <= end]


def meeting_items(meeting: dict, agenda_html: bytes) -> list[dict]:
    soup = BeautifulSoup(agenda_html, "html.parser")
    day = meeting["date"].isoformat()
    items: list[dict] = []
    section = None
    current = None
    for el in soup.find_all(["td", "a"]):
        if el.name == "td" and "numberspace" in (el.get("class") or []):
            label = el.get_text(strip=True).rstrip(".")
            body = el.find_next_sibling("td")
            text = re.sub(r"\s+", " ", body.get_text(" ", strip=True)) if body else ""
            if re.fullmatch(r"[IVXL]+", label):
                section, current = text, None
            elif label.isdigit():
                if section and "CLOSED SESSION" in section.upper():
                    current = None  # litigation and personnel conferences; nothing public to summarize
                    continue
                number = label if not any(i["item_number"] == label for i in items) else f"{label}b"
                current = {
                    "id": f"airports-{day}-{number}",
                    "commission": "airports",
                    "meeting_date": day,
                    "item_number": number,
                    "title": re.sub(r"^RESOLUTION NO\.?\s*-\s*", "", text)[:200],
                    "text": f"[{section}]\n{text}" if section else text,
                    "urls": [meeting["agenda_url"]],
                }
                items.append(current)
            elif current is not None and text:
                current["text"] += f"\n{label}. {text}"
        elif el.name == "a" and current is not None and "MetaViewer" in (el.get("href") or ""):
            current["urls"].append(el["href"])
    return items
