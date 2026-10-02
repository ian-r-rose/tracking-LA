"""Cultural Affairs Commission: meeting records only.

https://culture.lacity.gov/commission-meetings embeds an Airtable shared view listing
agendas and minutes. The view's data is readable through the request the embed itself
makes, but the attached PDFs need Airtable's signed download flow, so agenda contents
aren't fetched: each meeting becomes one item saying when it met and what was posted.
"""

import html
import re
from datetime import date, datetime

import httpx

PAGE = "https://culture.lacity.gov/commission-meetings"
NOTE = "[Cultural Affairs Commission meeting. Agenda contents aren't retrievable automatically; see the commission page.]"


def _view_data(client: httpx.Client) -> dict:
    page = client.get(PAGE)
    page.raise_for_status()
    share = re.search(r"airtable\.com/embed/(shr\w+)", page.text).group(1)
    embed = client.get(f"https://airtable.com/embed/{share}")
    embed.raise_for_status()
    text = embed.text.replace("\\u002F", "/")
    url = html.unescape(re.search(r'(/v0\.3/view/[^"\\]+readSharedViewData\?[^"\\]+)', text).group(1))
    app = re.search(r'"x-airtable-application-id":"(\w+)"', text).group(1)
    resp = client.get(
        "https://airtable.com" + url,
        headers={"x-airtable-application-id": app, "x-requested-with": "XMLHttpRequest", "x-time-zone": "America/Los_Angeles"},
    )
    resp.raise_for_status()
    return resp.json()["data"]["table"]


def parse_view(table: dict) -> list[dict]:
    """One meeting per date with an agenda, skipping dates with a cancelled agenda."""
    cols = {c["name"]: c for c in table["columns"]}
    types = {k: v["name"] for k, v in cols["Document Type"]["typeOptions"]["choices"].items()}
    records = []
    for row in table["rows"]:
        cells = row["cellValuesByColumnId"]
        when = cells.get(cols["Meeting Date"]["id"])
        if not when:
            continue
        files = cells.get(cols["Document"]["id"]) or []
        records.append(
            {
                "date": datetime.fromisoformat(when.replace("Z", "+00:00")).date(),
                "title": cells.get(cols["Title"]["id"], ""),
                "kind": types.get(cells.get(cols["Document Type"]["id"]), ""),
                "filename": files[0]["filename"] if files else "",
            }
        )
    cancelled = {r["date"] for r in records if "cancel" in (r["title"] + r["filename"]).lower()}
    minutes = {r["date"] for r in records if r["kind"] == "Meeting Minutes"}
    meetings = {}
    for r in records:
        if r["kind"] == "Meeting Agenda" and r["date"] not in cancelled:
            meetings.setdefault(r["date"], {
                "commission": "cac",
                "date": r["date"],
                "agenda_url": f"{PAGE}#{r['date'].isoformat()}",
                "agenda_title": r["title"],
                "agenda_file": r["filename"],
                "has_minutes": r["date"] in minutes,
            })
    return sorted(meetings.values(), key=lambda m: m["date"], reverse=True)


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    return [m for m in parse_view(_view_data(client)) if start <= m["date"] <= end]


def meeting_items(meeting: dict, _page: bytes) -> list[dict]:
    day = meeting["date"].isoformat()
    text = f"{NOTE}\nAgenda: {meeting['agenda_title']} ({meeting['agenda_file']})"
    if meeting["has_minutes"]:
        text += "\nMinutes have been posted."
    return [
        {
            "id": f"cac-{day}-meeting",
            "commission": "cac",
            "meeting_date": day,
            "item_number": "meeting",
            "title": f"Cultural Affairs Commission meeting, {meeting['date']:%B %-d, %Y}",
            "text": text,
            "urls": [PAGE],
        }
    ]
