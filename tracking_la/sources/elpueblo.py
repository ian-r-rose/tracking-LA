"""El Pueblo de Los Angeles Historical Monument Authority Commission.

https://elpueblo.lacity.gov/commission shows only the latest meeting: its agenda, the
previous meeting's minutes, and supporting documents (lease key terms, staff
recommendations). There's no archive, so each meeting is captured while it's posted.
"""

import re
from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from tracking_la.pdf import normalize_space, pdf_text

PAGE = "https://elpueblo.lacity.gov/commission"

# Agenda items rarely name a place because the whole commission is about one; say where it is
# so extraction can locate every item.
CONTEXT = "[El Pueblo de Los Angeles Historical Monument (Olvera Street), 125 Paseo de la Plaza]"

# Action items are numbered within a section: "3.8 Recommendation to Approve ..."
ITEM_START = re.compile(r"^\s{0,8}(\d\.\d{1,2})\s+(\S.*)$")
ITEM_END = re.compile(r"^\s*(COMMISSION BUSINESS|ADJOURNMENT|\d\.\s{2,}[A-Z])")
STOPWORDS = {"the", "and", "for", "with", "approval", "recommendation", "approve", "lease", "report", "authorize"}


def parse_page(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    links = [(a.get_text(" ", strip=True), urljoin(PAGE, a["href"])) for a in soup.select("a[href]")]
    agenda = next(((t, u) for t, u in links if re.search(r"commission agenda", t, re.I)), None)
    if not agenda or not (m := re.search(r"(\d{1,2})-(\d{1,2})-(\d{2})", agenda[0])):
        return None
    month, day, year = (int(g) for g in m.groups())
    when = date(2000 + year, month, day)
    files = [(t, u) for t, u in links if "/files/" in u and u != agenda[1]]
    return {
        "body": "elpueblo",
        "date": when,
        "agenda_url": agenda[1],
        # Listed minutes are for the previous meeting, so they aren't attached to these items.
        "documents": [{"title": t, "url": u} for t, u in files if f"{when:%Y-%m}" in u and "minutes" not in t.lower()],
    }


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(PAGE)
    resp.raise_for_status()
    meeting = parse_page(resp.text)
    return [meeting] if meeting and start <= meeting["date"] <= end else []


def split_agenda(text: str) -> list[tuple[str, str]]:
    items: list[tuple[str, list[str]]] = []
    current = None
    for line in text.splitlines():
        if m := ITEM_START.match(line):
            current = [m.group(2)]
            items.append((m.group(1), current))
        elif ITEM_END.match(line):
            current = None
        elif current is not None and line.strip():
            current.append(line)
    return [(number, normalize_space("\n".join(lines))) for number, lines in items]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def _codes(text: str) -> set[str]:
    """Acronyms and space codes (UNAM, C-10), plus initialisms of capitalized phrases, so
    "Olvera Street Merchants Association Foundation" also yields "OSMAF"."""
    codes = set(re.findall(r"\b(?:[A-Z]{3,}|[A-Z]-\d+)\b", text))
    for run in re.findall(r"(?:[A-Z][a-z]+\s+){2,}[A-Z][a-z]+", text):
        initials = "".join(w[0] for w in run.split())
        codes |= {initials[i:j] for i in range(len(initials)) for j in range(i + 3, len(initials) + 1)}
    return codes


def _match_score(title: str, item_text: str) -> int:
    return len(_words(title) & _words(item_text)) + 2 * len(_codes(title) & _codes(item_text))


def items_from_text(meeting: dict, agenda_text: str) -> list[dict]:
    day = meeting["date"].isoformat()
    items = []
    for number, text in split_agenda(agenda_text):
        items.append(
            {
                "id": f"elpueblo-{day}-{number}",
                "body": "elpueblo",
                "meeting_date": day,
                "item_number": number,
                "title": text.splitlines()[0],
                "text": f"{CONTEXT}\n{text}",
                "urls": [meeting["agenda_url"]],
            }
        )
    # Attach each supporting document to the item whose text shares the most words with its title
    # (e.g. "Olvera Street Gates Recommendation" -> "... Entrance Security Gates at Olvera Street").
    for doc in meeting["documents"]:
        scored = [(_match_score(doc["title"], item["text"]), item) for item in items]
        best_score, best = max(scored, key=lambda s: s[0], default=(0, None))
        if best and best_score >= 2:
            best["urls"].append(doc["url"])
    return items


def meeting_items(meeting: dict, agenda_pdf: bytes) -> list[dict]:
    return items_from_text(meeting, pdf_text(agenda_pdf))
