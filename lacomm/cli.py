import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta

import httpx
import yaml

from lacomm.check import check_all
from lacomm.geo import Geocoder, Neighborhoods
from lacomm.sources import planning
from lacomm.store import DATA, upsert_item

USER_AGENT = "la-commissions/0.1"


def fetch(since_days: int) -> None:
    start = date.today() - timedelta(days=since_days)
    counts = Counter()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        meetings = []
        for year in range(start.year, date.today().year + 2):
            meetings += planning.list_meetings(year, client)
        for meeting in meetings:
            if meeting["date"] < start:
                continue
            resp = client.get(meeting["agenda_url"])
            resp.raise_for_status()
            for item in planning.meeting_items(meeting, resp.content):
                counts[upsert_item(item)] += 1
            counts["meetings"] += 1
    print(", ".join(f"{k}: {v}" for k, v in counts.items()) or "nothing found")


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="lacomm")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="Fetch agendas for meetings since N days ago (and all upcoming)")
    p.add_argument("--since", type=int, default=30, metavar="DAYS")
    sub.add_parser("check", help="Validate item files (run after extraction)")
    sub.add_parser("locate", help="Geocode item locations and assign neighborhoods")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.since)
    elif args.command == "locate":
        locate()
    elif args.command == "check":
        bad = check_all()
        print(f"{bad} item file(s) with problems" if bad else "all items OK")
        sys.exit(1 if bad else 0)
