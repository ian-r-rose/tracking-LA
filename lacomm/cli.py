import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import httpx
import yaml

from lacomm import USER_AGENT
from lacomm.check import check_all
from lacomm.geo import Geocoder, Neighborhoods
from lacomm.score import candidates
from lacomm.sources import planning
from lacomm.store import DATA, upsert_item

# The Planning server takes ~9s per request regardless of size, so download a few at a time.
CONCURRENT_DOWNLOADS = 4

# Agenda URLs already processed, so past meetings aren't downloaded again.
AGENDAS = DATA / "agendas.json"


def fetch(since_days: int) -> None:
    today = date.today()
    start = today - timedelta(days=since_days)
    seen: dict = json.loads(AGENDAS.read_text()) if AGENDAS.exists() else {}
    counts = Counter()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        # Next year's schedule only appears late in the year.
        last_year = today.year + 1 if today.month == 12 else today.year
        meetings = [m for year in range(start.year, last_year + 1) for m in planning.list_meetings(year, client)]
        # Upcoming agendas can still be revised, so always re-fetch those.
        todo = [m for m in meetings if m["date"] >= start and (m["date"] >= today or m["agenda_url"] not in seen)]
        counts["skipped"] = sum(1 for m in meetings if m["date"] >= start) - len(todo)

        def download(meeting):
            resp = client.get(meeting["agenda_url"])
            resp.raise_for_status()
            return meeting, resp.content

        try:
            with ThreadPoolExecutor(CONCURRENT_DOWNLOADS) as pool:
                for meeting, pdf in pool.map(download, todo):
                    for item in planning.meeting_items(meeting, pdf):
                        counts[upsert_item(item)] += 1
                    seen[meeting["agenda_url"]] = meeting["date"].isoformat()
                    counts["fetched"] += 1
        finally:
            AGENDAS.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n")
    print(", ".join(f"{k}: {v}" for k, v in counts.items() if v) or "nothing found")


def locate() -> None:
    interests = yaml.safe_load((DATA.parent / "config" / "interests.yaml").read_text())
    hoods = Neighborhoods()
    counts = Counter()
    near_me = []
    with httpx.Client(timeout=30) as client:
        geocoder = Geocoder(client)
        try:
            for path in sorted((DATA / "items").rglob("*.json")):
                item = json.loads(path.read_text())
                for loc in item.get("locations", []):
                    counts["locations"] += 1
                    if "lat" not in loc and (hit := geocoder.geocode(loc["text"])):
                        loc.update(lat=hit["lat"], lon=hit["lon"], neighborhood=hoods.containing(hit["lat"], hit["lon"]))
                        path.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
                    counts["located" if "lat" in loc else "unresolved"] += 1
                    if "lat" in loc and (hits := hoods.nearby(loc["lat"], loc["lon"], interests["neighborhoods"], interests["nearby_km"])):
                        near_me.append((item["id"], loc["text"], loc.get("neighborhood"), hits))
        finally:
            geocoder.save()
    print(", ".join(f"{k}: {v}" for k, v in counts.items()), f"(new lookups: {geocoder.lookups})")
    for item_id, text, hood, hits in near_me:
        print(f"  near {', '.join(hits)}: {item_id}  {text}  [{hood}]")


def score(limit: int) -> None:
    ranked = candidates()
    for c in ranked[:limit]:
        print(f"{c['score']:3}  {c['path']}  [{'; '.join(c['reasons'])}]")
        print(f"     {c['meeting_date']}  {c['summary']}")
    print(f"{len(ranked)} undigested item(s)")


def mark_digested(digest_date: str) -> None:
    ranked = candidates()
    for c in ranked:
        path = DATA.parent / c["path"]
        item = json.loads(path.read_text())
        item["digest"] = digest_date
        path.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
    print(f"marked {len(ranked)} item(s) as covered by the {digest_date} digest")


def main() -> None:
    parser = argparse.ArgumentParser(prog="lacomm")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="Fetch agendas for meetings since N days ago (and all upcoming)")
    p.add_argument("--since", type=int, default=30, metavar="DAYS")
    sub.add_parser("check", help="Validate item files (run after extraction)")
    sub.add_parser("locate", help="Geocode item locations and assign neighborhoods")
    p = sub.add_parser("score", help="Rank items not yet in a digest")
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("mark-digested", help="Record that all undigested items were covered by a digest")
    p.add_argument("date", help="Digest date, YYYY-MM-DD")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.since)
    elif args.command == "locate":
        locate()
    elif args.command == "score":
        score(args.limit)
    elif args.command == "mark-digested":
        mark_digested(args.date)
    elif args.command == "check":
        bad = check_all()
        print(f"{bad} item file(s) with problems" if bad else "all items OK")
        sys.exit(1 if bad else 0)
