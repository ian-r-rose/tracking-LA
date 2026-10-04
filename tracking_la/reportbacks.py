"""Report backs: Council instructions to a department to look into something and report
back, and whether the report has come in.

The instructions are in the motions on watched committees' Council Files ("I THEREFORE
MOVE that the Council instruct the Department of Transportation to report back within
30 days on ..."). Clerk Connect has a "Report Back" activity type, but it is almost
never used, so the motions themselves are read: the fetch keeps each motion's operative
paragraphs, and the routine's review (ROUTINE.md) records the requests in them. The
clock starts when Council adopts the motion.

A document on the Council File after adoption whose title names an asked department
("Report from Department of Transportation") is a candidate report; the fetch keeps
the start of its text, and the routine checks whether it answers the request. Until
then it's an unconfirmed filing. A committee scheduling a verbal update on the matter
counts as a report.

data/report-backs/<council file>.json has, from the fetch: council_file, title,
introduced, motion_url, motion (its MOVE paragraphs), adopted (date or null) and
documents ([{date, title, url, excerpt}], dated on or after adoption; url is null for
a verbal update, and excerpt is only kept for candidate reports). From the routine:
requests, a list of {departments, asks, deadline}, where deadline is a number of days,
a date ("YYYY-MM-DD") or null ([] when the motion asks for no report back), and
document_reviews, {document url: [indexes of the requests it answers]}.
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
EXCERPT_CHARS = 3000
# Documents on a Council File that are never a department's report.
NOT_A_REPORT = re.compile(
    r"^(Council Action|Mayor Concurrence|(Amending )?Motion|Speaker Card|Communications?(\(s\))? from Public$|"
    r"Community Impact Statement|Proof of Publication|Declaration of Posting|Oath|Resolution|Report from .*Committee$|"
    r"Attachment to|Final Ordinance|Communication from (Committee Chair|Deputy Clerk|City Clerk))",
    re.I,
)


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


def online_documents(soup: BeautifulSoup) -> list[tuple[date, str, str]]:
    """(doc date, title, URL) from a Clerk Connect page's Online Documents list, newest first.
    The page repeats the list (once per tab), so each URL is kept once."""
    docs = {}
    for row in soup.select("tr"):
        cells = row.find_all("td")
        link = cells[0].find("a", href=True) if len(cells) == 2 else None
        when = cells[1].get_text(strip=True) if link else ""
        if re.fullmatch(r"\d\d/\d\d/\d{4}", when) and link["href"] not in docs:
            docs[link["href"]] = (datetime.strptime(when, "%m/%d/%Y").date(), link.get_text(" ", strip=True), link["href"])
    return list(docs.values())


def parse_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = next((l.find_next(class_="rectext") for l in soup.select(".reclabel") if l.get_text(strip=True) == "Title"), None)
    docs = online_documents(soup)
    motions = [url for _, name, url in docs if re.match(r"Motion\b", name)]
    activities = sorted(council.file_activities(soup), key=lambda a: a[0])  # oldest first
    adopted = next((d for d, a in activities if a.startswith("Council adopted")), None)
    documents = []
    if adopted:
        documents = [
            {"date": d.isoformat(), "title": name, "url": url}
            for d, name, url in docs if d >= adopted and not NOT_A_REPORT.match(name)
        ] + [
            {"date": d.isoformat(), "title": a, "url": None}
            for d, a in activities if d >= adopted and re.search(r"scheduled a verbal update", a, re.I)
        ]
        documents.sort(key=lambda doc: doc["date"])
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
    return record.get("requests") is None or any(not confirmed(record, i) for i in range(len(record["requests"])))


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
    excerpts = {doc["url"]: doc["excerpt"] for doc in record.get("documents", []) if "excerpt" in doc}
    for doc in page["documents"]:
        if doc["url"] in excerpts:
            doc["excerpt"] = excerpts[doc["url"]]
        elif doc["url"] and any(candidate(doc, q) for q in record.get("requests") or []):
            resp = client.get(doc["url"])
            resp.raise_for_status()
            doc["excerpt"] = re.sub(r"\s+", " ", pdf_text(resp.content)).strip()[:EXCERPT_CHARS]
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


def names(department: str) -> set[str]:
    """A department's name and the other names its reports are filed under."""
    full = canonical(department)
    return {full} | {alias for alias, name in ALIASES.items() if name == full}


def candidate(doc: dict, request: dict) -> bool:
    """Whether a document could be the report: its title names an asked department, or it's
    from the Mayor, who transmits many departments' reports."""
    title = canonical(doc["title"])
    if re.search(r"\bfrom mayor\b", title):
        return True
    return any(re.search(rf"\b{re.escape(n)}\b", title) for d in request["departments"] for n in names(d))


def filed(record: dict, index: int) -> tuple[dict, bool] | None:
    """The report for the record's `index`th request, and whether the routine confirmed it:
    the first document the routine found answers it, or an unchecked candidate before that,
    or a verbal update."""
    reviews = record.get("document_reviews", {})
    for doc in record.get("documents", []):
        if doc["url"] is None:
            return doc, True
        if doc["url"] in reviews:
            if index in reviews[doc["url"]]:
                return doc, True
        elif candidate(doc, record["requests"][index]):
            return doc, False
    return None


def confirmed(record: dict, index: int) -> dict | None:
    return (found := filed(record, index)) and found[1] and found[0]


def to_review(record: dict) -> list[dict]:
    """Candidate reports the routine hasn't checked yet."""
    reviews = record.get("document_reviews", {})
    return [
        doc for doc in record.get("documents", [])
        if doc["url"] and doc["url"] not in reviews and any(candidate(doc, q) for q in record.get("requests") or [])
    ]


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


def table(today: date, root: Path = DATA) -> list[tuple[dict, dict, dict | None, bool]]:
    """(record, request, report or None, confirmed) for adopted instructions still pending,
    or filed within SHOW_FILED_FOR, most recently adopted first."""
    rows = []
    for r in records(root):
        for i, q in enumerate(r.get("requests") or [] if r.get("adopted") else []):
            doc, ok = filed(r, i) or (None, False)
            if not doc or date.fromisoformat(doc["date"]) >= today - SHOW_FILED_FOR:
                rows.append((r, q, doc, ok))
    return sorted(rows, key=lambda row: row[0]["adopted"], reverse=True)


def landed(root: Path = DATA) -> list[tuple[str, dict, dict, dict]]:
    """(request id, record, request, report) for every request whose report the routine confirmed."""
    return [
        (request_id(r, i), r, q, doc)
        for r in records(root) if r.get("adopted")
        for i, q in enumerate(r.get("requests") or []) if (doc := confirmed(r, i))
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
    urls = {doc["url"] for doc in record.get("documents", [])}
    for url, answers in record.get("document_reviews", {}).items():
        if url not in urls:
            problems.append(f"document_reviews names a document that isn't in documents: {url}")
        if not isinstance(answers, list) or not all(isinstance(i, int) and 0 <= i < len(requests) for i in answers):
            problems.append(f"document_reviews values must list indexes into requests (0 to {len(requests) - 1}): {answers!r}")
    return problems
