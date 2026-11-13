"""City Council and its committees, from the City Clerk's Legislative Management System.

Committees are where Council matters are discussed before going to full Council; a
committee's action is a recommendation to Council.

Full Council passes nearly everything in batches, a section per roll call, unless an
item is called "special"; there's no consent marker on an item. Its agendas skip
closed sessions, nuisance-abatement liens (the -0160-S series of Council Files) and
motions funding a district's events and recognitions. An item whose Council File was
on a watched committee's agenda `follows` that committee item: it carries over the
committee item's extraction instead of being extracted again, and isn't followed for
a decision itself, since the committee item records Council's action.

The LMS (https://lms.lacity.gov/) replaced both the Clerk's PrimeGov portal and Clerk
Connect in October 2026; the portal's last agendas are for October 28. Its pages sit
behind a firewall (AWS WAF) that challenges most requests, but two things don't:

- the public list of meetings, as JSON (/api/public/meetings?format=json), which has
  each meeting's body, date, status and agenda PDF;
- the agenda PDFs themselves, on the Clerk's CloudFront domain.

So meetings and agendas come from those. An agenda PDF heads each item "Item 7 · CF
26-0742 ... CD 10", from which come the item's number, Council File and district.

Each item belongs to a Council File, the City's id for a matter as it moves between
committees and Council. Decisions come from the file's page in the LMS, whose Timeline
records every step, including what full Council did after the committee, and whose
Votes have roll calls by member. Those pages are behind the firewall (see FilePages).
"""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from tracking_la.outcomes import normalize_status
from tracking_la.pdf import pdf_text
from tracking_la.store import DATA

LMS_MEETINGS = "https://lms.lacity.gov/api/public/meetings"
LMS_FILE = "https://lms.lacity.gov/files/{}"

# The LMS's name for each body we watch. It lists meetings from before it launched too,
# imported from PrimeGov; those are already recorded from PrimeGov, under other ids.
BODIES = {
    "planning-and-land-use-management": "council-plum",
    "transportation": "council-transportation",
    "arts-parks-and-city-facilities-committee": "council-arts-parks",
    "public-works": "council-public-works",
    "housing-committee": "council-housing",
    "homelessness-and-health-committee": "council-homelessness",
    "energy-and-environment": "council-environment",
    "council": "council",  # full City Council
}
LMS_SINCE = date(2026, 10, 29)
MAX_PAGES = 40  # of ten past meetings each; a year of full Council

# Full Council has met with a regular agenda plus special ones; only a few days back,
# since what it did comes from the LMS's file pages, not agendas.
COUNCIL_LOOKBACK = timedelta(days=3)

SKIP_COUNCIL_ITEM = re.compile(
    r"may recess to Closed Session"
    r"|relative to funding for (services in connection with|.*\b(celebration|recognition|observation|commemoration)\b)",
    re.I,
)
LIEN_FILE = re.compile(r"^\d{2}-0160-S\d+$")  # nuisance-abatement liens


def council_file_url(number: str) -> str:
    return LMS_FILE.format(number)


class Challenged(httpx.HTTPError):
    """The LMS's firewall (AWS WAF) wants a browser to prove itself: status 202, an empty
    body and an x-amzn-waf-action header. We don't try to get past it. The page stays as
    recorded and a later fetch reads it, if the firewall lets that one through."""


def challenged(resp: httpx.Response) -> bool:
    return resp.status_code == 202 or "x-amzn-waf-action" in resp.headers


def meeting_id(slug: str, lms_body: str) -> str:
    """A short id from an LMS meeting's slug, which is the date it was first scheduled
    for, its body, and a number when the body has several that day: "2026-10-30-council-3"
    is "20261030-3". A rescheduled meeting keeps its slug."""
    return slug.replace(f"-{lms_body}", "", 1).replace("-", "", 2)


def parse_meetings(raw: list[dict]) -> list[dict]:
    """Meetings of watched bodies with an agenda, from the LMS's records. A meeting that
    was imported from PrimeGov lists its extra agendas (continuation, special) under
    `agendas`; the LMS's own are separate meetings."""
    meetings, seen = [], set()
    for m in raw:
        body = BODIES.get(m["body"])
        if not body or m["status"] == "cancelled":
            continue
        for agenda in m.get("agendas") or [m]:
            slug = agenda["url"].rsplit("/", 1)[-1]
            if agenda["meetingType"] == "cancellation" or not agenda.get("agendaPdfUrl") or slug in seen:
                continue
            seen.add(slug)
            meetings.append(
                {
                    "body": body,
                    "name": m["name"],
                    "date": date.fromisoformat(m["date"]),
                    "meeting_id": meeting_id(slug, m["body"]),
                    "agenda_url": agenda["agendaPdfUrl"],  # a revision is a new PDF, so it's fetched again
                    "page_url": agenda["url"],
                }
            )
    return meetings


def lms_meetings(lms_body: str, start: date, client: httpx.Client) -> list[dict]:
    """The LMS's records of a body's meetings back to `start`, and every body's upcoming
    ones (`body` only narrows the past ones, which come ten to a page, newest first)."""
    raw = []
    for page in range(1, MAX_PAGES + 1):
        resp = client.get(LMS_MEETINGS, params={"format": "json", "body": lms_body, "page": page})
        if challenged(resp):
            raise Challenged(f"the LMS's firewall challenged its list of meetings ({resp.url})")
        resp.raise_for_status()
        data = resp.json()
        past = data["past"]["meetings"]
        raw += past + (data["upcoming"]["meetings"] if page == 1 else [])
        if not past or not data["past"]["nextUrl"] or min(m["date"] for m in past) < start.isoformat():
            break
    return raw


def list_meetings(start: date, end: date, client: httpx.Client) -> list[dict]:
    start = max(start, LMS_SINCE)
    council_start = max(start, date.today() - COUNCIL_LOOKBACK)
    raw = []
    for lms_body, body in BODIES.items():
        raw += lms_meetings(lms_body, council_start if body == "council" else start, client)
    return [
        m for m in parse_meetings(raw)
        if (council_start if m["body"] == "council" else start) <= m["date"] <= end
    ]


def _short(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3].rsplit(" ", 1)[0] + "…"


def committee_items(root: Path = DATA) -> dict[str, list[tuple[str, str]]]:
    """(meeting date, item id) of watched committees' items, by Council File."""
    found = {}
    for path in (root / "items").glob("council-*/*/*.json"):
        item = json.loads(path.read_text())
        if m := re.match(r"\[Council File ([^;\]]+)", item["text"]):
            found.setdefault(m.group(1), []).append((item["meeting_date"], item["id"]))
    return found


# "Item 7 · CF 26-0742          CD 10" (or "Citywide"); an item can lack a Council File.
ITEM = re.compile(r"^\s*Item (\w+) ·\s*(?:CF (\d{2}-\d{4}(?:-S\d+)?))?\s*(.*?)\s*$")
# "Items for which Public Hearings Have Been Held        19 items"
SECTION = re.compile(r"^(\S.*?)\s{3,}\d+ items?\s*$")
# "City Council      - November 10, 2026 -      Page 4 of 28", at the foot of each page.
PAGE_FOOTER = re.compile(r"^(\S.*?)\s+- [A-Z][a-z]+ \d{1,2}, \d{4} -\s+Page \d+ of \d+\s*$")
# What follows the last item: Council's closing business, or a committee's notices.
END_OF_ITEMS = re.compile(
    r"^(MOTIONS FOR POSTING AND REFERRAL|COUNCIL MEMBERS' REQUESTS FOR EXCUSE|ADJOURNING MOTIONS|COUNCIL ADJOURNMENT"
    r"|ADJOURNMENT|Notice to Paid Representatives|Reasonable Modifications? or Acc|Council Process)"
)
# An item's two-column fields: the label on the left (wrapped: "Community impact" /
# "statement"), the value on the right.
FIELD = re.compile(r"^(Fiscal impact statement|Community impact)\s{2,}(\S.*)$")
FIELD_LABELS = {"Fiscal impact statement": "Fiscal Impact Statement:", "Community impact": "Community Impact Statement:"}
# Lines that start a new line of an item even without a blank line before them.
NEW_LINE = re.compile(r"^(\d{1,2}\.\s|[a-z]\.\s|(Applicant|Representative|Owner|Appellant|Case Nos?\.|Environmental|Related Cases?)\b)")


def agenda_lines(text: str, name: str) -> list[str]:
    """An agenda's lines without the page footers, which fall in the middle of items, and
    the blank lines around them, unless the page ended with a sentence: a paragraph that
    runs over the page stays whole. A long body name wraps onto a second footer line
    ("Planning and Land Use Management", then "Committee")."""
    lines, rest, after_footer = [], None, False
    for line in text.replace("\f", "\n").splitlines():
        if m := PAGE_FOOTER.match(line):
            rest = name[len(m.group(1)):].strip() if name.startswith(m.group(1)) else None
            while lines and not lines[-1].strip():
                lines.pop()
            if not lines or lines[-1].rstrip().endswith((".", ":", ";", ")")):
                lines.append("")
            after_footer = True
        elif after_footer and (not line.strip() or line.strip() == rest):
            continue
        else:
            after_footer = False
            lines.append(line)
    return lines


def reflow(lines: list[str]) -> list[str]:
    """An item's wrapped lines as paragraphs, numbered recommendations and labelled fields."""
    out, paragraph = [], []

    def flush():
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            flush()
        elif m := FIELD.match(raw.strip()):
            flush()
            out.append(FIELD_LABELS[m.group(1)])
            paragraph.append(re.sub(r"\s+", " ", m.group(2)))
        elif line != "statement":  # the rest of "Community impact statement"
            if NEW_LINE.match(line):
                flush()
            paragraph.append(line)
            if line.endswith(":"):
                flush()
    flush()
    return out


def agenda_items(text: str, name: str = "") -> list[tuple[str, str | None, str | None, str | None, list[str]]]:
    """(item number, Council File, district, section, lines) for each item of an agenda PDF's text."""
    items, section, current, lines = [], None, None, agenda_lines(text, name)
    for n, line in enumerate(lines):
        if m := ITEM.match(line):
            number, council_file, where = m.groups()
            current = []
            items.append((number, council_file, where if re.fullmatch(r"CDs? [\d, ]+", where) else None, section, current))
        elif m := SECTION.match(line):
            heading, current = m.group(1), None
            for more in lines[n + 1:]:  # a long heading wraps
                if not more.strip() or ITEM.match(more):
                    break
                heading += " " + more.strip()
            section = None if heading == "Item(s)" else heading  # most committee agendas' only section
        elif items and END_OF_ITEMS.match(line):
            break
        elif current is not None:
            current.append(line)
    return [(number, council_file, district, section, reflow(body)) for number, council_file, district, section, body in items]


def meeting_items(meeting: dict, agenda_pdf: bytes, root: Path = DATA) -> list[dict]:
    council = meeting["body"] == "council"
    followed = committee_items(root) if council else {}
    items = []
    for number, council_file, district, section, lines in agenda_items(pdf_text(agenda_pdf), meeting.get("name", "")):
        if council and (SKIP_COUNCIL_ITEM.search(lines[0] if lines else "") or LIEN_FILE.match(council_file or "")):
            continue
        header = "; ".join(p for p in (f"Council File {council_file}" if council_file else None, district) if p)
        item = {
            "id": f"{meeting['body']}-{meeting['date'].isoformat()}-{meeting['meeting_id']}-{number}",
            "body": meeting["body"],
            "meeting_date": meeting["date"].isoformat(),
            "item_number": number,
            "title": _short(lines[0] if lines else f"Item {number}"),
            "text": "\n".join(p for p in (f"[{header}]" if header else None, f"[{section}]" if section else None, *lines) if p),
            "urls": [meeting["agenda_url"], *([council_file_url(council_file)] if council_file else [])],
        }
        earlier = [c for c in followed.get(council_file, []) if c[0] <= item["meeting_date"]]
        if earlier:
            item["follows"] = max(earlier)[1]
        items.append(item)
    return items


# File Activities that record a decision (most record scheduling, referrals, documents
# received or transmittals instead).
ACTION = re.compile(
    r"\b(adopted|approved|continued|denied|disapproved|noted and filed|received and filed|granted|"
    r"concurred|withdrawn|vetoed|failed|signed|tabled)\b",
    re.I,
)


DATE = re.compile(r"[A-Z][a-z]{2} \d{1,2}, \d{4}")  # "Oct 7, 2026"


def tab(soup: BeautifulSoup, name: str):
    """One of an LMS file page's tabs (timeline, documents, votes), all on the page."""
    return soup.find(id=re.compile(rf"-content-{name}$"))


class FilePages:
    """LMS file pages for one run. Outcomes and report backs share them, so each page is
    requested once, and nothing more is requested once the firewall has challenged us."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.pages: dict[str, str] = {}
        self.unread: set[str] = set()

    def get(self, url: str) -> str:
        if url in self.pages:
            return self.pages[url]
        if self.unread:
            self.unread.add(url)
            raise Challenged(f"not requested after a challenge: {url}")
        resp = self.client.get(url)
        if challenged(resp):
            self.unread.add(url)
            raise Challenged(f"challenged: {url}")
        resp.raise_for_status()
        self.pages[url] = resp.text
        return resp.text

    def report(self, failed: list) -> None:
        if self.unread:
            failed.append(
                f"lms.lacity.gov: its firewall challenged the fetch (AWS WAF), so {len(self.unread)} Council File "
                "page(s) weren't read; what's recorded stands until a later fetch reads them"
            )


class NotAFilePage(ValueError):
    """A page that isn't an LMS file page, such as an error or maintenance page. Reading it
    as a file with no activity would blank what's recorded, as a firewall challenge's empty
    page once did to every followed report back."""


def file_page(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    if not soup.find("h1") or not tab(soup, "timeline"):
        raise NotAFilePage("not a Council File page (no title or timeline)")
    return soup


# A committee's own action, not Council's ("Council action: Adopted Planning and Land Use
# Committee Report").
COMMITTEE_ACTION = re.compile(r"^(?!Council\b)[^:]*\bCommittee\b")


def file_activities(soup: BeautifulSoup) -> list[tuple[date, str]]:
    """(date, activity) from an LMS file page's Timeline, newest first. The page lists
    them twice (major events and all activity), so each is kept once. Some activities
    say what was done in a second paragraph ("City Council action:" / "Adopted"), which
    is joined to the first. The LMS says "City Council" where Clerk Connect
    said "Council"; activities keep Clerk Connect's wording, so outcomes recorded from
    it don't change."""
    activities = {}
    for row in tab(soup, "timeline").find_all("li") if tab(soup, "timeline") else []:
        when = row.find("span", string=DATE)
        text = row.find("p")
        if when and text:
            text = text.get_text(" ", strip=True)
            if text.endswith(":") and (detail := row.find("p").find_next_sibling("p")):
                text += " " + detail.get_text(" ", strip=True)
            text = re.sub(r"^City Council\b", "Council", re.sub(r"\s+", " ", text))
            activities.setdefault((datetime.strptime(when.get_text(strip=True), "%b %d, %Y").date(), text), None)
    return list(activities)


def council_votes(text: str) -> dict[date, str]:
    """Council roll-call tallies (ayes-noes-absent) by meeting date, e.g. {2025-12-12: "14-1-0"},
    from the text of an LMS file page's Votes."""
    votes = {}
    for when, ayes, noes, absent in re.findall(
        r"meeting of (\w+ \d{1,2}, \d{4})(?:(?!meeting of).)*?Ayes (\d+), Noes (\d+), Absent (\d+)", text, re.S
    ):
        votes.setdefault(datetime.strptime(when, "%B %d, %Y").date(), f"{ayes}-{noes}-{absent}")
    return votes


def council_file_outcome(html: str, url: str, since: date | None = None) -> dict | None:
    """The latest action on a Council File (by a committee or by Council) since `since`, the
    item's meeting date: a Council File can have been decided before, on an earlier motion.
    When Council acted on a committee's report, the committee's action comes first, since
    "Council adopted item" alone doesn't say what the committee recommended (e.g. whether
    PLUM granted or denied an appeal). Raises NotAFilePage for anything but a file page."""
    soup = file_page(html)
    activities = [(when, text.rstrip(" .")) for when, text in file_activities(soup) if not since or when >= since]
    actions = [(when, text) for when, text in activities if ACTION.search(text) and "transmitted" not in text.lower()]
    if not actions:
        return None
    when, text = max(actions, key=lambda a: a[0])  # File Activities are newest first; max keeps the first on a tie
    text = f"{text} ({when:%b %-d, %Y})"
    if text.startswith("Council ") and (
        committee := next(((w, t) for w, t in actions if w <= when and COMMITTEE_ACTION.match(t)), None)
    ):
        text = f"{committee[1]} ({committee[0]:%b %-d, %Y}); {text}"
    if any(w >= when and "Council action final" in t for w, t in activities):
        text += "; Council action final"  # past the Mayor's and Council's reconsideration windows
    outcome = {"status": normalize_status(text), "text": text, "source": url}
    if (votes_tab := tab(soup, "votes")) and when in (votes := council_votes(votes_tab.get_text(" "))):
        outcome["vote"] = votes[when]
    return outcome


def follow_url(item: dict) -> str | None:
    if item.get("follows"):  # the committee item it follows records Council's action
        return None
    return next((u for u in item["urls"] if u.startswith(LMS_FILE.format(""))), None)
