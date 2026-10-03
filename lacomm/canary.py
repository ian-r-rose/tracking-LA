"""Live check that every source still parses, so a changed site fails loudly.

The tests run against saved copies of agendas, so they can't notice a commission
redesigning its site. A redesign usually shows up as a listing with no meetings,
or agendas that download fine but split into no items. For each source this checks
that meetings are listed in a recent window and that one of the newest few
agendas yields items.
"""

from datetime import date, timedelta

import httpx

from lacomm.sources import SOURCES, Source

WINDOW = timedelta(days=120)  # long enough for bodies that meet every other month
TRIES = 3  # the newest agendas to try; one can legitimately be empty (closed session only)


def check_source(source: Source, client: httpx.Client, today: date) -> str | None:
    """A description of what's wrong with `source`, or None if it looks healthy."""
    meetings = source.list_meetings(today - WINDOW, today + timedelta(days=60), client)
    if not meetings:
        return f"no meetings listed since {today - WINDOW}"
    newest = sorted(meetings, key=lambda m: m["date"], reverse=True)[:TRIES]
    parse = source.canary_items or source.meeting_items
    for meeting in newest:
        resp = client.get(meeting["agenda_url"])
        resp.raise_for_status()
        if parse(meeting, resp.content):
            return None
    return f"the newest {len(newest)} agenda(s) produced no items: " + ", ".join(m["agenda_url"] for m in newest)


def run(client: httpx.Client, today: date | None = None) -> int:
    """Print a line per source; return the number of sources with problems."""
    today = today or date.today()
    problems = 0
    for source in SOURCES:
        try:
            problem = check_source(source, client, today)
        except Exception as e:  # a parser crashing on a changed page is exactly what we're looking for
            problem = f"{type(e).__name__}: {e}"
        problems += bool(problem)
        print(f"{'PROBLEM' if problem else 'ok':8} {source.name}" + (f": {problem}" if problem else ""))
    return problems
