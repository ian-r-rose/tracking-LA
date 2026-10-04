"""Every agenda source, behind one interface: list meetings in a date range, then
turn one meeting's agenda (raw bytes) into items. Sources that publish journals or
minutes can also say where a meeting's record is and how to read outcomes from it."""

from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Callable

from lacomm.pdf import pdf_text
from lacomm.sources import (
    airports, council, cultural, elpueblo, ens, harbor, lacers, library, metro, planning, planning_cases, primegov, rap,
    trees, zoo,
)


@dataclass
class Source:
    name: str
    list_meetings: Callable  # (start, end, client) -> list[meeting]
    meeting_items: Callable  # (meeting, agenda bytes) -> list[item]
    outcome_url: Callable | None = None  # (meeting) -> URL of its journal/minutes, or None
    meeting_outcomes: Callable | None = None  # (meeting, record bytes) -> {item id: outcome}
    # For lacomm canary, when meeting_items can legitimately return nothing (it filters):
    # (meeting, agenda bytes) -> items before filtering.
    canary_items: Callable | None = None
    # Sources whose items each have a page to follow for decisions (a Planning case in
    # PDIS, a Council File in Clerk Connect): item -> page URL or None, (page html, URL,
    # item) -> outcome or None, and how many days to keep re-checking after a decision.
    follow_url: Callable | None = None
    follow_outcome: Callable | None = None
    follow_days: int = 30


SOURCES = [
    Source(
        "planning", planning.list_meetings, planning.meeting_items,
        outcome_url=lambda m: m.get("minutes_url"),
        meeting_outcomes=lambda m, pdf: planning.minutes_outcomes(m, pdf_text(pdf)),
    ),
    Source(
        "public works", primegov.list_meetings, primegov.meeting_items,
        outcome_url=lambda m: m.get("journal_url"),
        meeting_outcomes=primegov.journal_outcomes,
    ),
    Source(
        "rec and parks", rap.list_meetings, rap.meeting_items,
        outcome_url=lambda m: m.get("minutes_url"),
        meeting_outcomes=lambda m, pdf: rap.minutes_outcomes(m, pdf_text(pdf)),
    ),
    Source("tree postings", trees.list_meetings, trees.meeting_items),
    Source(
        "planning cases", planning_cases.list_meetings, planning_cases.meeting_items,
        canary_items=lambda m, feed: planning_cases.project_items(feed),
        follow_url=lambda item: item["urls"][0] if item["body"] == "planning-cases" else None,
        follow_outcome=lambda html, url, item: planning_cases.case_outcome(html, url), follow_days=30,
    ),
    Source(
        "council committees", council.list_meetings, council.meeting_items,
        # Matters reach full Council weeks after the committee, so keep following longer.
        # Only actions from the item's meeting on: a Council File may have been decided before.
        follow_url=council.follow_url,
        follow_outcome=lambda html, url, item: council.council_file_outcome(html, url, date.fromisoformat(item["meeting_date"])),
        follow_days=90,
    ),
    Source("cultural affairs", cultural.list_meetings, cultural.meeting_items),
    Source("el pueblo", elpueblo.list_meetings, elpueblo.meeting_items),
    Source("zoo", zoo.list_meetings, zoo.meeting_items),
    Source("harbor", harbor.list_meetings, harbor.meeting_items),
    Source("airports", airports.list_meetings, airports.meeting_items),
    Source("library", library.list_meetings, library.meeting_items),
    Source("lacers", lacers.list_meetings, lacers.meeting_items),
    Source(
        "metro", metro.list_meetings, metro.meeting_items,
        outcome_url=lambda m: m["agenda_url"],
        meeting_outcomes=metro.meeting_outcomes,
    ),
    *(
        Source(fmt.body, partial(ens.list_meetings, fmt), partial(ens.meeting_items, fmt))
        for fmt in ens.FORMATS
    ),
]
