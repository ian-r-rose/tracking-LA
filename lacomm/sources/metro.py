"""Metro (LA County Metropolitan Transportation Authority) Board of Directors.

Not a City commission, but the City appoints four of its thirteen directors and it
decides most transit and highway projects in the City. Metro publishes through
Legistar, whose public API lists meetings (`/events`) and each meeting's items
(`/events/{id}/eventitems`) with the recommendation text, staff report attachments
and, once the Board has met, the action taken. Committees are separate bodies and
are skipped; their recommendations reach the Board as items.
"""

import json
import re
from datetime import date, datetime

import httpx

from lacomm.outcomes import normalize_status

API = "https://webapi.legistar.com/v1/metro"
BODIES = {"Board of Directors - Regular Board Meeting", "Board of Directors - Special Board Meeting"}
# Standing items with a matter number but nothing to decide.
SKIP = re.compile(r"^(APPROVE Minutes|RECEIVE remarks by the Chair|RECEIVE report by the Chief Executive Officer|RECEIVE General Public Comment)", re.I)
COMMITTEE = re.compile(r"COMMITTEE (MADE|FORWARDED) THE FOLLOWING", re.I)
# Minutes of earlier meetings ride along on some items but aren't about them.
SKIP_ATTACHMENT = re.compile(r"minutes", re.I)


def items_url(event_id: int) -> str:
    return f"{API}/events/{event_id}/eventitems?AgendaNote=1&MinutesNote=1&Attachments=1"


def parse_events(events: list[dict]) -> list[dict]:
    return [
        {
            "body": "metro",
            "date": datetime.fromisoformat(e["EventDate"]).date(),
            "agenda_url": items_url(e["EventId"]),
            "page_url": e["EventInSiteURL"],
        }
        for e in events
        if e["EventBodyName"] in BODIES and e["EventAgendaStatusName"] == "Final"
    ]


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    resp = client.get(
        f"{API}/events",
        params={"$filter": f"EventDate ge datetime'{start.isoformat()}' and EventDate le datetime'{end.isoformat()}'"},
    )
    resp.raise_for_status()
    return parse_events(resp.json())


def _number(item: dict) -> str:
    return (item["EventItemAgendaNumber"] or "").strip().rstrip(".")


def _decisions(event_items: list[dict]):
    """(item, committee recommendation heading or None) for each numbered item, in agenda order."""
    heading = None
    for item in sorted(event_items, key=lambda i: (i["EventItemAgendaSequence"] is None, i["EventItemAgendaSequence"] or 0)):
        title = (item["EventItemTitle"] or "").strip()
        if not _number(item):
            heading = title if COMMITTEE.search(title) else None
            continue
        if item["EventItemMatterId"] and not SKIP.match(title):
            yield item, heading
        heading = None


def item_id(meeting: dict, item: dict) -> str:
    return f"metro-{meeting['date'].isoformat()}-{_number(item)}"


def meeting_items(meeting: dict, content: bytes) -> list[dict]:
    items = []
    for item, heading in _decisions(json.loads(content)):
        title = re.sub(r"\s+", " ", item["EventItemTitle"]).strip()
        text = item["EventItemTitle"].replace("\r\n", "\n").strip()
        if heading:
            text = f"[{heading}]\n{text}"
        matter = f"https://metro.legistar.com/LegislationDetail.aspx?ID={item['EventItemMatterId']}&GUID={item['EventItemMatterGuid']}"
        attachments = [
            a["MatterAttachmentHyperlink"]
            for a in item["EventItemMatterAttachments"] or []
            if a["MatterAttachmentShowOnInternetPage"] and not SKIP_ATTACHMENT.search(a["MatterAttachmentName"])
        ]
        items.append(
            {
                "id": item_id(meeting, item),
                "body": "metro",
                "meeting_date": meeting["date"].isoformat(),
                "item_number": _number(item),
                "title": title if len(title) <= 160 else title[:157].rsplit(" ", 1)[0] + "…",
                "text": f"[Metro Board file {item['EventItemMatterFile']}, {item['EventItemMatterType']}]\n{text}",
                "urls": [meeting["page_url"], matter, *attachments],
            }
        )
    return items


def meeting_outcomes(meeting: dict, content: bytes) -> dict[str, dict]:
    outcomes = {}
    for item, _ in _decisions(json.loads(content)):
        if action := item["EventItemActionName"]:
            outcome = {"status": normalize_status(action), "text": action, "source": meeting["page_url"]}
            if item["EventItemTally"]:
                outcome["vote"] = item["EventItemTally"]
            outcomes[item_id(meeting, item)] = outcome
    return outcomes
