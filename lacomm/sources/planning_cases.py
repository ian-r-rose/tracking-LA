"""New City Planning case filings (entitlement applications).

Not a commission: these are applications as they're filed, weeks or months before
a hearing, and many are decided by a Zoning Administrator or the Planning Director
without one. Planning's "recent case filings" page reads a JSON feed covering about
two weeks. A project often files several cases at once (an environmental ENV case
alongside a ZA or DIR case), so cases with the same address and description become
one item, keyed by its main case number.

Unlike agendas, filings arrive citywide at a steady clip and are all site-specific,
so only projects in or near the watched neighborhoods are kept. A project whose
address doesn't geocode is kept too.
"""

import json
import re
from datetime import date, datetime

import httpx

from lacomm import http_client
from lacomm.geo import Geocoder, Neighborhoods
from lacomm.score import load_interests

FEED = "https://planning.lacity.gov/dcpapi/general/newcases"


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    today = date.today()
    return [{"commission": "planning-cases", "date": today, "agenda_url": f"{FEED}#{today.isoformat()}"}]


def _main_case(cases: list[dict]) -> dict:
    """The entitlement case rather than its environmental companion, when there is one."""
    return next((c for c in cases if not c["caseNum"].startswith(("ENV-", "EAR-"))), cases[0])


def _short(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "…"


def project_items(feed_json: bytes) -> list[tuple[str, dict]]:
    """(address, item) for each project in the feed."""
    projects: dict[tuple, list[dict]] = {}
    for case in json.loads(feed_json):
        key = (re.sub(r"\s+", " ", case["address"] or "").strip().upper(), (case["desc"] or "").strip())
        projects.setdefault(key, []).append(case)
    items = []
    for (address, desc), cases in projects.items():
        main = _main_case(cases)
        filed = datetime.strptime(main["date"], "%m/%d/%Y").date()
        numbers = sorted({c["caseNum"] for c in cases}, key=lambda n: n != main["caseNum"])
        lines = [
            f"Case numbers: {', '.join(numbers)}",
            f"Address: {address}" if address else "",
            f"Filed: {filed.isoformat()}",
            f"Council district: {main['cd']}" if main.get("cd") else "",
            f"Community plan area: {main['cpa']}" if main.get("cpa") else "",
            f"Description: {desc}" if desc else "",
        ]
        item = {
            "id": f"plncase-{main['caseNum']}",
            "commission": "planning-cases",
            "meeting_date": filed.isoformat(),
            "item_number": main["caseNum"],
            "title": _short(f"{address}: {desc}" if desc else f"{address} ({main['caseNum']})"),
            "text": "[New City Planning case filing (application, not yet decided)]\n" + "\n".join(l for l in lines if l),
            "urls": [c["url"] for c in sorted(cases, key=lambda c: c["caseNum"] != main["caseNum"])],
        }
        items.append((address, item))
    return items


def is_local(address: str, geocoder: Geocoder, hoods: Neighborhoods, interests: dict) -> bool:
    if not (hit := geocoder.geocode(f"{address}, Los Angeles, CA")):
        return True
    return bool(hoods.nearby(hit["lat"], hit["lon"], interests["neighborhoods"], interests["nearby_km"]))


def meeting_items(meeting: dict, feed_json: bytes) -> list[dict]:
    interests, hoods = load_interests(), Neighborhoods()
    with http_client(timeout=30) as client:
        geocoder = Geocoder(client)
        try:
            return [item for address, item in project_items(feed_json) if is_local(address, geocoder, hoods, interests)]
        finally:
            geocoder.save()
