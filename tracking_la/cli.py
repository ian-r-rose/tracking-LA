import argparse
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

import httpx
import yaml

from tracking_la import http_client
from tracking_la import canary
from tracking_la import digested as digested_csv
from tracking_la import reportbacks
from tracking_la.check import check_all
from tracking_la.outcomes import PROCESSED, normalize_status, record
from tracking_la.geo import Geocoder, Neighborhoods, Places, build_places
from tracking_la.score import candidates
from tracking_la.site import build as build_site
from tracking_la.sources import SOURCES, Source
from tracking_la.store import DATA, upsert_item

# The Planning server takes ~9s per request regardless of size, so download a few at a time.
CONCURRENT_DOWNLOADS = 4

# Agenda URLs already processed, so past meetings aren't downloaded again.
AGENDAS = DATA / "agendas.json"

# How far ahead to look for posted agendas.
LOOKAHEAD = timedelta(days=60)


def fetch(since_days: int, refetch: bool = False, only: str | None = None) -> None:
    today = date.today()
    start, end = today - timedelta(days=since_days), today + LOOKAHEAD
    seen: dict = json.loads(AGENDAS.read_text()) if AGENDAS.exists() else {}
    counts = Counter()
    failed, empty = [], []
    with http_client(timeout=60) as client:
        todo = []
        for source in SOURCES:
            if only and source.name != only:
                continue
            try:
                meetings = source.list_meetings(start, end, client)
            except httpx.HTTPError as e:
                failed.append(f"{source.name}: {e}")
                continue
            # Upcoming agendas can still be revised, so always re-fetch those.
            new = [m for m in meetings if refetch or m["date"] >= today or m["agenda_url"] not in seen]
            counts["skipped"] += len(meetings) - len(new)
            todo += [(source, m) for m in new]

        def download(job):
            source, meeting = job
            try:
                resp = client.get(meeting["agenda_url"])
                resp.raise_for_status()
                return source, meeting, resp.content
            except httpx.HTTPError as e:
                failed.append(f"{meeting['agenda_url']}: {e}")
                return source, meeting, None

        try:
            with ThreadPoolExecutor(CONCURRENT_DOWNLOADS) as pool:
                for source, meeting, content in pool.map(download, todo):
                    if content is None:
                        continue
                    items = source.meeting_items(meeting, content)
                    if not items and not source.canary_items:  # a filtering source can come up empty
                        empty.append(meeting["agenda_url"])
                    for item in items:
                        counts[upsert_item(item)] += 1
                    seen[meeting["agenda_url"]] = meeting["date"].isoformat()
                    counts["fetched"] += 1
        finally:
            AGENDAS.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n")
    print(", ".join(f"{k}: {v}" for k, v in counts.items() if v) or "nothing found")
    for url in empty:
        print(f"  empty: {url} produced no items (a format change, or nothing but standing items)")
    for failure in failed:
        print(f"  failed: {failure}")
    if failed:
        sys.exit(1)


# Journals and minutes can be revised shortly after a meeting; re-read them for this long.
OUTCOME_RECHECK = timedelta(days=14)
# Stop following a page once it shows a final decision, or when its item is this old.
FINAL = re.compile(r"Council action final", re.I)
FOLLOW_AT_MOST = timedelta(days=365)


def followed_outcomes(client: httpx.Client, counts: Counter, failed: list) -> None:
    """Decisions for items that each have a page to follow (Source.follow_url): a Planning
    case's PDIS page, a Council File's Clerk Connect page. Each page is fetched once per
    run, even when several items share it (a Council File on several agendas)."""
    today = date.today()
    followers = [s for s in SOURCES if s.follow_url]
    pages: dict[str, tuple[Source, list[Path]]] = {}
    for path in sorted((DATA / "items").rglob("*.json")):
        item = json.loads(path.read_text())
        if date.fromisoformat(item["meeting_date"]) < today - FOLLOW_AT_MOST:
            continue
        for source in followers:
            if not (url := source.follow_url(item)):
                continue
            o = item.get("outcome")
            final = o and FINAL.search(o["text"])
            stale = o and date.fromisoformat(o["recorded"]) < today - timedelta(days=source.follow_days)
            if not (final or stale):
                pages.setdefault(url, (source, []))[1].append(path)
            break

    def fetch_page(url):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return url, resp.text
        except httpx.HTTPError as e:
            failed.append(f"{url}: {e}")
            return url, None

    with ThreadPoolExecutor(CONCURRENT_DOWNLOADS) as pool:
        for url, html in pool.map(fetch_page, list(pages)):
            counts["pages followed"] += 1
            source, paths = pages[url]
            for path in paths if html else []:
                outcome = source.follow_outcome(html, url, json.loads(path.read_text()))
                if outcome and record(path, outcome):
                    counts["followed decisions recorded"] += 1


def outcomes(since_days: int) -> None:
    today = date.today()
    start = today - timedelta(days=since_days)
    processed: dict = json.loads(PROCESSED.read_text()) if PROCESSED.exists() else {}
    counts = Counter()
    failed = []
    with http_client(timeout=60) as client:
        for source in SOURCES:
            if not source.meeting_outcomes:
                continue
            try:  # one unreachable site shouldn't stop the others
                for meeting in source.list_meetings(start, today - timedelta(days=1), client):
                    url = source.outcome_url(meeting)
                    if not url or (url in processed and meeting["date"] < today - OUTCOME_RECHECK):
                        continue
                    resp = client.get(url)
                    resp.raise_for_status()
                    for item_id, outcome in source.meeting_outcomes(meeting, resp.content).items():
                        path = DATA / "items" / meeting["body"] / item_id.split("-")[1] / f"{item_id}.json"
                        if not path.exists():
                            counts["no matching item"] += 1
                        elif record(path, {"status": normalize_status(outcome["text"]), **outcome}):  # a parser's own status wins
                            counts["recorded"] += 1
                        else:
                            counts["unchanged"] += 1
                    processed[url] = meeting["date"].isoformat()
                    counts["records read"] += 1
            except httpx.HTTPError as e:
                failed.append(f"{source.name}: {e}")
        followed_outcomes(client, counts, failed)
        reportbacks.update(client, counts, failed)
    PROCESSED.write_text(json.dumps(processed, indent=1, sort_keys=True) + "\n")
    print(", ".join(f"{k}: {v}" for k, v in counts.items()) or "no new journals or minutes")
    for failure in failed:
        print(f"  failed: {failure}")
    if failed:
        sys.exit(1)


def decisions(digest_date: str) -> None:
    """Outcomes not yet reported in a digest (or reported in the `digest_date` one, so a
    digest can be rewritten); items flagged in an earlier digest first."""
    found = []
    digested = digested_csv.load()
    for path in sorted((DATA / "items").rglob("*.json")):
        item = json.loads(path.read_text())
        if (o := item.get("outcome")) and digested.get((item["id"], o["recorded"]), digest_date) == digest_date:
            found.append((not item.get("flag"), item["meeting_date"], path, item, o))
    for _, _, path, item, o in sorted(found, key=lambda f: (f[0], f[1])):
        flagged = "*" if item.get("flag") else " "
        print(f"{flagged} {o['status']:10} {o.get('vote', ''):5} {path.relative_to(DATA.parent)}")
        print(f"     {item['meeting_date']}  {item.get('summary', item['title'])[:120]}  [{o['text']}]")
    print(f"{len(found)} unreported outcome(s); * = flagged in a digest")


def locate() -> None:
    interests = yaml.safe_load((DATA.parent / "config" / "interests.yaml").read_text())
    hoods = Neighborhoods()
    places = Places()
    counts = Counter()
    near_me = []
    with http_client(timeout=30) as client:
        geocoder = Geocoder(client)
        try:
            for path in sorted((DATA / "items").rglob("*.json")):
                item = json.loads(path.read_text())
                for loc in item.get("locations", []):
                    counts["locations"] += 1
                    if "lat" not in loc:
                        point = places.lookup(loc["text"])
                        if not point and (hit := geocoder.geocode(loc["text"])):
                            point = hit["lat"], hit["lon"]
                        if point:
                            loc.update(lat=point[0], lon=point[1], neighborhood=hoods.containing(*point))
                        path.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
                    counts["located" if "lat" in loc else "unresolved"] += 1
                    if "lat" in loc and (hits := hoods.nearby(loc["lat"], loc["lon"], interests["neighborhoods"], interests["nearby_km"])):
                        near_me.append((item["id"], loc["text"], loc.get("neighborhood"), hits))
        finally:
            geocoder.save()
    print(", ".join(f"{k}: {v}" for k, v in counts.items()), f"(new lookups: {geocoder.lookups})")
    for item_id, text, hood, hits in near_me:
        print(f"  near {', '.join(hits)}: {item_id}  {text}  [{hood}]")


def la_today() -> str:
    """Digests are dated in LA time; the routine's machine runs on UTC."""
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def score(limit: int | None, digest_date: str) -> None:
    """One line per item for the digest, so the digest step can review all of them cheaply."""
    ranked = candidates(digest_date=digest_date)
    for c in ranked[:limit]:
        reasons = f" [{'; '.join(c['reasons'])}]" if c["reasons"] else ""
        print(f"{c['score']:2} {c['meeting_date']} {c['path']}{reasons} {c['summary']}")
    print(f"{len(ranked)} item(s) for the {digest_date} digest (not yet in a digest, or already in this one)")


def report_backs(digest_date: str) -> None:
    """Report backs that came in and aren't in a digest yet (or are in the `digest_date` one),
    then how many are still pending."""
    digested = digested_csv.load()
    found = [
        (rid, r, q, doc) for rid, r, q, doc in reportbacks.landed()
        if digested.get((rid, doc["date"]), digest_date) == digest_date
    ]
    for rid, r, q, doc in sorted(found, key=lambda f: f[3]["date"], reverse=True):
        when = reportbacks.due(r, q)
        late = f"{(date.fromisoformat(doc['date']) - when).days:+d} days vs due {when}" if when else "no deadline"
        print(f"{doc['date']}  {r['council_file']:12} {doc['from']} ({late}); adopted {r['adopted']}")
        print(f"     asked {', '.join(q['departments'])}: {q['asks']}")
        print(f"     {reportbacks.council.council_file_url(r['council_file'])}")
    pending = [(r, q) for r, q, doc in reportbacks.table(date.fromisoformat(digest_date)) if not doc]
    overdue = [rq for rq in pending if (d := reportbacks.due(*rq)) and d < date.fromisoformat(digest_date)]
    unreviewed = sum(1 for r in reportbacks.records() if r.get("motion") and r.get("requests") is None)
    print(f"{len(found)} report back(s) came in; {len(pending)} pending ({len(overdue)} overdue)"
          + (f"; {unreviewed} motion(s) not yet reviewed" if unreviewed else ""))


def mark_digested(digest_date: str) -> None:
    """Record in data/digested.csv that every extracted item, decision and report back not
    yet in a digest was covered by this one."""
    digested = digested_csv.load()
    rows = []
    for path in sorted((DATA / "items").rglob("*.json")):
        item = json.loads(path.read_text())
        if "summary" in item and (item["id"], "") not in digested:
            rows.append((digest_date, item["id"], ""))
        if (o := item.get("outcome")) and (item["id"], o["recorded"]) not in digested:
            rows.append((digest_date, item["id"], o["recorded"]))
    report_backs = [(digest_date, rid, doc["date"]) for rid, _, _, doc in reportbacks.landed() if (rid, doc["date"]) not in digested]
    digested_csv.append(rows + report_backs)
    items = sum(1 for r in rows if not r[2])
    print(f"marked {items} item(s), {len(rows) - items} outcome(s) and {len(report_backs)} report back(s)"
          f" as covered by the {digest_date} digest")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tracking-la")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="Fetch agendas for meetings since N days ago (and all upcoming)")
    p.add_argument("--since", type=int, default=30, metavar="DAYS")
    p.add_argument("--refetch", action="store_true", help="Re-download past agendas too (e.g. after a parser fix)")
    p.add_argument("--source", choices=[s.name for s in SOURCES], help="Fetch only this source")
    p = sub.add_parser("outcomes", help="Record decisions from journals and minutes of past meetings")
    p.add_argument("--since", type=int, default=60, metavar="DAYS")
    p = sub.add_parser("decisions", help="List recorded outcomes not yet reported in a digest")
    p.add_argument("--date", default=la_today(), help="Digest date; outcomes already in it are listed too (default: today in LA)")
    sub.add_parser("check", help="Validate item files (run after extraction)")
    sub.add_parser("canary", help="Check against the live sites that every source still lists meetings and parses items")
    sub.add_parser("locate", help="Geocode item locations and assign neighborhoods")
    sub.add_parser("build-places", help="Refresh geo/places.json from Rec & Parks data on LA GeoHub")
    p = sub.add_parser("score", help="Rank items not yet in a digest")
    p.add_argument("--limit", type=int, help="Show only the top N (default: all)")
    p.add_argument("--date", default=la_today(), help="Digest date; items already in it are listed too (default: today in LA)")
    p = sub.add_parser("report-backs", help="List report backs that came in and aren't in a digest yet")
    p.add_argument("--date", default=la_today(), help="Digest date; report backs already in it are listed too (default: today in LA)")
    p = sub.add_parser("mark-digested", help="Record that all undigested items were covered by a digest")
    p.add_argument("date", help="Digest date, YYYY-MM-DD")
    p = sub.add_parser("site", help="Build the static site")
    p.add_argument("--out", default="_site")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.since, args.refetch, args.source)
    elif args.command == "locate":
        locate()
    elif args.command == "build-places":
        with http_client(timeout=120) as client:
            print(f"{build_places(client)} places")
    elif args.command == "score":
        score(args.limit, args.date)
    elif args.command == "mark-digested":
        mark_digested(args.date)
    elif args.command == "outcomes":
        outcomes(args.since)
    elif args.command == "decisions":
        decisions(args.date)
    elif args.command == "report-backs":
        report_backs(args.date)
    elif args.command == "site":
        print(f"built {args.out}/ with {build_site(Path(args.out))} digest(s)")
    elif args.command == "canary":
        with http_client(timeout=120) as client:
            problems = canary.run(client)
        print(f"{problems} source(s) with problems" if problems else "all sources OK")
        sys.exit(1 if problems else 0)
    elif args.command == "check":
        bad = check_all()
        print(f"{bad} item file(s) with problems" if bad else "all items OK")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
