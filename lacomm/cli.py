import argparse
from collections import Counter
from datetime import date, timedelta

import httpx

from lacomm.sources import planning
from lacomm.store import upsert_item

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="lacomm")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch", help="Fetch agendas for meetings since N days ago (and all upcoming)")
    p.add_argument("--since", type=int, default=30, metavar="DAYS")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.since)
