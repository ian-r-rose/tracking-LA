"""Board of Recreation and Park Commissioners, from Rec & Parks' own site.

https://recreation.parks.lacity.gov/commissioners/agendas-minutes-reports/<year> lists
each meeting with its agenda, minutes, numbered board reports (26-213.pdf), and other
documents such as commissioner motions and presentations, which aren't agenda items
in the PDF but can matter (e.g. a motion opposing use of park land for a project).

A firewall in front of the site (an AWS load balancer) sometimes refuses requests from
cloud machines such as GitHub's runners, with a 403. Then the agendas come from
ens.lacity.org instead, without minutes or extra documents, and only for meetings not
already fetched from the site, whose fuller items they would otherwise replace. Once the
site answers again, its agenda (a different URL) is fetched and its versions of the
items replace the fallback ones.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from tracking_la import http_client
from tracking_la.store import DATA
from tracking_la.pdf import normalize_space, pdf_text
from tracking_la.sources import ens
from tracking_la.sources.ens import RECREATION_AND_PARKS, split_agenda

SITE = "https://recreation.parks.lacity.gov"
YEAR_PAGE = SITE + "/commissioners/agendas-minutes-reports/{year}"
REPORT_NUMBER = re.compile(r"^\d{2}-\d{3}$")

# Bundles of public comment letters from residents: not Board actions.
SKIP_DOCUMENT = re.compile(r"documents?[ -]received|constituent", re.IGNORECASE)

# Extra documents get the start of their own text as item text; enough for extraction.
EXTRA_TEXT_CHARS = 4000


def parse_year_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    meetings = []
    for row in soup.select("tr.agenda-minutes"):
        when = row.find("time")
        cells = row.find_all("td")
        agenda = cells[1].find("a") if len(cells) > 1 else None
        if not when or not agenda or "cancel" in agenda.get_text().lower():
            continue
        minutes = cells[2].find("a") if len(cells) > 2 else None
        documents = []
        details = row.find_next_sibling("tr")
        if details and not details.has_attr("class"):
            for a in details.select("div.reports a[href]"):
                documents.append({"title": a.get_text(" ", strip=True), "url": urljoin(SITE, a["href"])})
        meetings.append(
            {
                "body": "rap",
                "date": datetime.fromisoformat(when["datetime"].replace("Z", "+00:00")).date(),
                "agenda_url": urljoin(SITE, agenda["href"]),
                "minutes_url": urljoin(SITE, minutes["href"]) if minutes else None,
                "documents": documents,
            }
        )
    return meetings


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    try:
        return site_meetings(start, end, client)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 403:
            raise
        print(
            f"  fallback: rec and parks refused {e.request.url} (403 from {e.response.headers.get('server')}) "
            f"for IP {public_ip(client)}; using ens.lacity.org agendas, without minutes or extra documents"
        )
        meetings = ens.list_meetings(RECREATION_AND_PARKS, start, end, client)
        return [m | {"fallback": True} for m in meetings if not from_site(m["date"])]


def from_site(day: date, root: Path = DATA) -> bool:
    """Whether this meeting's items were fetched from Rec & Parks' own site."""
    for path in (root / "items" / "rap" / str(day.year)).glob(f"rap-{day.isoformat()}-*.json"):
        if any(url.startswith(SITE) for url in json.loads(path.read_text())["urls"]):
            return True
    return False


def public_ip(client: httpx.Client) -> str:
    """This machine's public IP, to tell whether the firewall refuses particular addresses."""
    try:
        return client.get("https://checkip.amazonaws.com", timeout=10).text.strip()
    except httpx.HTTPError:
        return "unknown"


def site_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    meetings = []
    for year in range(start.year, end.year + 1):
        resp = client.get(YEAR_PAGE.format(year=year))
        resp.raise_for_status()
        meetings += [m for m in parse_year_page(resp.text) if start <= m["date"] <= end]
    return meetings


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def items_from_meeting(meeting: dict, agenda_text: str, extra_texts: dict[str, str]) -> list[dict]:
    """Board reports from the agenda, plus one item per extra document (keyed by URL in extra_texts)."""
    day = meeting["date"].isoformat()
    shared_urls = [meeting["agenda_url"]] + ([meeting["minutes_url"]] if meeting.get("minutes_url") else [])
    reports = {d["title"]: d["url"] for d in meeting["documents"] if REPORT_NUMBER.match(d["title"])}
    items = []
    for number, text, _section in split_agenda(RECREATION_AND_PARKS, agenda_text):
        items.append(
            {
                "id": f"rap-{day}-{number}",
                "body": "rap",
                "meeting_date": day,
                "item_number": number,
                "title": text.splitlines()[0],
                "text": text,
                "urls": shared_urls + ([reports[number]] if number in reports else []),
            }
        )
    for doc in meeting["documents"]:
        if REPORT_NUMBER.match(doc["title"]) or SKIP_DOCUMENT.search(doc["title"]) or doc["url"] not in extra_texts:
            continue
        slug = _slug(doc["title"])
        items.append(
            {
                "id": f"rap-{day}-{slug}",
                "body": "rap",
                "meeting_date": day,
                "item_number": slug,
                "title": doc["title"],
                "text": f"[{doc['title']}]\n{extra_texts[doc['url']]}",
                "urls": shared_urls + [doc["url"]],
            }
        )
    return items


def meeting_items(meeting: dict, agenda_pdf: bytes) -> list[dict]:
    if meeting.get("fallback"):
        return ens.meeting_items(RECREATION_AND_PARKS, meeting, agenda_pdf)
    extra_texts = {}
    with http_client(timeout=60) as client:
        for doc in meeting["documents"]:
            if REPORT_NUMBER.match(doc["title"]) or SKIP_DOCUMENT.search(doc["title"]):
                continue
            resp = client.get(doc["url"])
            resp.raise_for_status()
            if resp.content.startswith(b"%PDF"):  # some PDFs are linked without a .pdf extension
                extra_texts[doc["url"]] = normalize_space(pdf_text(resp.content))[:EXTRA_TEXT_CHARS]
    return items_from_meeting(meeting, pdf_text(agenda_pdf), extra_texts)


def minutes_outcomes(meeting: dict, minutes_text: str) -> dict[str, dict]:
    """Outcomes by item id from meeting minutes: each board report is followed by a
    "DISPOSITION:" line, and votes are recorded in motion paragraphs that list report numbers."""
    day = meeting["date"].isoformat()
    outcomes: dict[str, dict] = {}
    current = None
    for line in minutes_text.splitlines():
        if m := re.match(r"^\s{0,3}(\d{2}-\d{3})\s{2,}\S", line):
            current = m.group(1)
        elif current and (m := re.match(r"^\s*DISPOSITION:\s*(.+)$", line)):
            outcomes[f"rap-{day}-{current}"] = {"text": m.group(1).strip(), "source": meeting["minutes_url"]}
            current = None
    for paragraph in re.split(r"\n\s*\n", minutes_text):
        if vote := re.search(r"vote of (\d+-\d+)", paragraph):
            for number in re.findall(r"\b\d{2}-\d{3}\b", paragraph):
                if (item_id := f"rap-{day}-{number}") in outcomes:
                    outcomes[item_id]["vote"] = vote.group(1)
    return outcomes
