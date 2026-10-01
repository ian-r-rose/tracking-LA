"""Every agenda source, behind one interface: list meetings in a date range, then
turn one meeting's agenda (raw bytes) into items."""

from dataclasses import dataclass
from functools import partial
from typing import Callable

from lacomm.sources import elpueblo, ens, planning, primegov, rap


@dataclass
class Source:
    name: str
    list_meetings: Callable  # (start, end, client) -> list[meeting]
    meeting_items: Callable  # (meeting, agenda bytes) -> list[item]


SOURCES = [
    Source("planning", planning.list_meetings, planning.meeting_items),
    Source("public works", primegov.list_meetings, primegov.meeting_items),
    Source("rec and parks", rap.list_meetings, rap.meeting_items),
    Source("el pueblo", elpueblo.list_meetings, elpueblo.meeting_items),
    *(
        Source(fmt.commission, partial(ens.list_meetings, fmt), partial(ens.meeting_items, fmt))
        for fmt in ens.FORMATS
    ),
]
