"""Report backs: Council instructions to a department to look into something and report
back, and whether the report has come in.

The instructions are in the motions on watched committees' Council Files ("I THEREFORE
MOVE that the Council instruct the Department of Transportation to report back within
30 days on ..."). Clerk Connect has a "Report Back" activity type, but it is almost
never used, so the motions themselves are read: the fetch keeps each motion's operative
paragraphs, and the routine's review (ROUTINE.md) records the requests in them. The
clock starts when Council adopts the motion. A report has come in when an asked
department files a document on the Council File afterwards, or a committee schedules
a verbal update.

data/report-backs/<council file>.json has, from the fetch: council_file, title,
introduced, motion_url, motion (its MOVE paragraphs), adopted (date or null) and
documents ([{date, from}], filed after adoption). From the review: requests, a list
of {departments, asks, deadline}, where deadline is a number of days, a date
("YYYY-MM-DD") or null; [] when the motion asks for no report back.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from tracking_la.pdf import pdf_text
from tracking_la.sources import council
from tracking_la.store import DATA

REPORT_BACKS = DATA / "report-backs"
FETCHED_FIELDS = ("council_file", "title", "introduced", "motion_url", "motion", "adopted", "documents")
# Older motions are left out, and a file stops being followed once its motion is this
# old without Council adopting it, or its adoption is this old.
TRACK_FOR = timedelta(days=730)
# Report backs that came in stay in the table this long.
SHOW_FILED_FOR = timedelta(days=365)
MOTION_CHARS = 4000


def record_path(council_file: str, root: Path = DATA) -> Path:
    return root / "report-backs" / f"{council_file}.json"


def council_files(root: Path = DATA) -> set[str]:
    """Council Files that have been on a watched committee's agenda."""
    files = set()
    for path in (root / "items").glob("council-*/*/*.json"):
        if url := council.follow_url(json.loads(path.read_text())):
            files.add(url.rsplit("cfnumber=", 1)[1])
    return files


def operative_text(text: str) -> str:
    """A motion's MOVE paragraphs (the instructions), or its start if it has none (a bad scan)."""
    text = re.sub(r"\s+", " ", text).strip()
    start = re.search(r"\b(I|WE)( THEREFORE| FURTHER)? MOVE\b", text)
    return (text[start.start():] if start else text)[:MOTION_CHARS]


def submitters(activity: str) -> list[str]:
    """Who filed a document, from a File Activity: "Document submitted by Bureau of
    Sanitation, dated ...", or "... by the Mayor, City Administrative Officer report dated ..."
    (the Mayor transmitting a department's report). A verbal update counts too."""
    if m := re.match(r"Documents? ?(?:\(s\))? submitted by (?:the Mayor, (.+?) report dated|(.+?)(?:, dated|, as follows|\.?$))", activity):
        return [s.strip() for s in (m.group(1) or m.group(2)).split(";") if s.strip()]
    if re.search(r"scheduled a verbal update", activity, re.I):
        return ["verbal update"]
    return []


def parse_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = next((l.find_next(class_="rectext") for l in soup.select(".reclabel") if l.get_text(strip=True) == "Title"), None)
    motions = [
        a["href"] for a in soup.select("a[href]")
        if a["href"].lower().endswith(".pdf") and (row := a.find_parent("tr")) and re.match(r"Motion\b", row.get_text(" ", strip=True))
    ]
    activities = sorted(council.file_activities(soup), key=lambda a: a[0])  # oldest first
    adopted = next((d for d, a in activities if a.startswith("Council adopted")), None)
    documents = [
        {"date": d.isoformat(), "from": who}
        for d, a in activities if adopted and d >= adopted for who in submitters(a)
    ]
    return {
        "title": re.sub(r"\s+", " ", title.get_text(" ", strip=True)) if title else None,
        "introduced": activities[0][0].isoformat() if activities else None,
        "motion_url": motions[-1] if motions else None,  # newest first, so the original motion is last
        "adopted": adopted.isoformat() if adopted else None,
        "documents": documents,
    }


def following(record: dict, today: date) -> bool:
    if not record.get("motion_url") or record.get("requests") == []:
        return False
    started = record.get("adopted") or record.get("introduced")
    if started and date.fromisoformat(started) < today - TRACK_FOR:
        return False
    return record.get("requests") is None or any(not filed(record, r) for r in record["requests"])


def refresh(record: dict, client: httpx.Client, today: date) -> dict:
    """The record with the Council File's page (and, when new, its motion) read again."""
    resp = client.get(council.council_file_url(record["council_file"]))
    resp.raise_for_status()
    page = parse_page(resp.text)
    if "introduced" not in record and page["introduced"] and date.fromisoformat(page["introduced"]) < today - TRACK_FOR:
        page["motion_url"] = None  # too old to track; the record just says so
    if page["motion_url"] and page["motion_url"] != record.get("motion_url"):
        motion = client.get(page["motion_url"])
        motion.raise_for_status()
        page["motion"] = operative_text(pdf_text(motion.content))
    return {**record, **page}


def update(client: httpx.Client, counts, failed: list, today: date | None = None, root: Path = DATA) -> None:
    """Create or refresh the record of each followed Council File."""
    today = today or date.today()
    (root / "report-backs").mkdir(exist_ok=True)
    todo = []
    for council_file in sorted(council_files(root)):
        path = record_path(council_file, root)
        record = json.loads(path.read_text()) if path.exists() else {"council_file": council_file}
        if not path.exists() or following(record, today):
            todo.append((path, record))

    def job(path_record):
        path, record = path_record
        try:
            return path, record, refresh(record, client, today)
        except httpx.HTTPError as e:
            failed.append(f"{council.council_file_url(record['council_file'])}: {e}")
            return path, record, None

    with ThreadPoolExecutor(4) as pool:
        for path, record, new in pool.map(job, todo):
            counts["Council Files read for report backs"] += 1
            if new and (new != record or not path.exists()):
                path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
                counts["report-back records updated"] += 1


# Clerk Connect names departments in full; motions often abbreviate. Boards and
# commissions file their departments' reports.
ALIASES = {
    "ladot": "department of transportation", "dot": "department of transportation",
    "board of transportation commissioners": "department of transportation",
    "lasan": "bureau of sanitation", "sanitation": "bureau of sanitation",
    "boe": "bureau of engineering", "bss": "bureau of street services", "streetsla": "bureau of street services",
    "bsl": "bureau of street lighting",
    "lahd": "housing department", "housing and community investment department": "housing department",
    "ladbs": "department of building and safety", "dbs": "department of building and safety",
    "ladwp": "department of water and power", "dwp": "department of water and power",
    "board of water and power commissioners": "department of water and power",
    "cao": "city administrative officer", "cla": "chief legislative analyst",
    "rap": "department of recreation and parks", "board of recreation and park commissioners": "department of recreation and parks",
    "dcp": "department of city planning", "city planning": "department of city planning",
    "city planning commission": "department of city planning",
    "lafd": "fire department", "lapd": "police department", "board of police commissioners": "police department",
    "gsd": "general services department", "lahsa": "homeless services authority",
}


def canonical(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name.lower())
    name = re.sub(r"\b(the|los angeles|city of|l\.a\.)\b|[^a-z ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return ALIASES.get(name, name)


def filed(record: dict, request: dict) -> dict | None:
    """The first document filed after adoption by one of the request's departments."""
    asked = {canonical(d) for d in request["departments"]}
    return next(
        (doc for doc in record.get("documents", []) if doc["from"] == "verbal update" or canonical(doc["from"]) in asked),
        None,
    )


def due(record: dict, request: dict) -> date | None:
    deadline = request.get("deadline")
    if isinstance(deadline, int) and record.get("adopted"):
        return date.fromisoformat(record["adopted"]) + timedelta(days=deadline)
    if isinstance(deadline, str):
        return date.fromisoformat(deadline)
    return None


def records(root: Path = DATA) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((root / "report-backs").glob("*.json"))]


def request_id(record: dict, index: int) -> str:
    return f"report-back:{record['council_file']}:{index}"


def table(today: date, root: Path = DATA) -> list[tuple[dict, dict, dict | None]]:
    """(record, request, filed document or None) for adopted instructions still pending, or
    filed within SHOW_FILED_FOR: pending first (overdue first, then by due date, then those
    without a deadline, oldest first), then filed ones, most recent first."""
    rows = [
        (r, q, filed(r, q)) for r in records(root) if r.get("adopted")
        for q in r.get("requests") or []
    ]
    pending = [row for row in rows if not row[2]]
    recent = [row for row in rows if row[2] and date.fromisoformat(row[2]["date"]) >= today - SHOW_FILED_FOR]
    pending.sort(key=lambda row: (due(row[0], row[1]) is None, due(row[0], row[1]) or date.max, row[0]["adopted"]))
    recent.sort(key=lambda row: row[2]["date"], reverse=True)
    return pending + recent


def landed(root: Path = DATA) -> list[tuple[str, dict, dict, dict]]:
    """(request id, record, request, document) for every request whose report has come in."""
    return [
        (request_id(r, i), r, q, doc)
        for r in records(root) if r.get("adopted")
        for i, q in enumerate(r.get("requests") or []) if (doc := filed(r, q))
    ]


def check_record(path: Path) -> list[str]:
    try:
        record = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]
    requests = record.get("requests")
    if requests is None:
        return []
    if not isinstance(requests, list):
        return ["requests must be a list"]
    problems = []
    for q in requests:
        if not isinstance(q, dict) or not q.get("asks") or not isinstance(q.get("departments"), list) or not q["departments"]:
            problems.append(f"each request needs departments (a non-empty list) and asks: {q!r}")
            continue
        deadline = q.get("deadline")
        if deadline is not None and not isinstance(deadline, int):
            try:
                datetime.strptime(str(deadline), "%Y-%m-%d")
            except ValueError:
                problems.append(f"deadline must be a number of days, a YYYY-MM-DD date or null: {deadline!r}")
    return problems
