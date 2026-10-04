"""Outcomes: what a commission decided on an item, from its journal or minutes.

Each item can get an `outcome`:
    {"status": "approved", "text": "REPORT ADOPTED, FORTHWITH", "vote": "5-0",
     "source": "<journal or minutes URL>", "recorded": "YYYY-MM-DD"}
`status` is normalized for filtering; `text` keeps the commission's own wording.
Note that under Charter §245 most board approvals can still be taken up by Council.
"""

import json
import re
from datetime import date
from pathlib import Path

from lacomm.store import DATA

# Minutes and journals already processed, so they aren't parsed again every run.
PROCESSED = DATA / "outcome-sources.json"


def normalize_status(text: str) -> str:
    t = text.upper()
    for pattern, status in [
        (r"CONTINUED|POSTPONED|DEFERRED|HELD", "continued"),
        (r"WITHDRAWN|PULLED|ADMINISTRATIVE CLOSURE|TERMINATED", "withdrawn"),
        (r"DENIED|DISAPPROVED|REJECTED|FAILED|VETOED", "denied"),
        (r"RECEIVED|NOTED AND FILED|\bFILED\b", "filed"),
        (r"ADOPTED|APPROVED|AWARDED|GRANTED|CONCURRED|SIGNED", "approved"),
    ]:
        if re.search(pattern, t):
            return status
    return "other"


def record(item_path: Path, outcome: dict) -> bool:
    """Set an item's outcome. Returns True if it changed. A later digest reports it once."""
    item = json.loads(item_path.read_text())
    old = item.get("outcome") or {}
    if {k: v for k, v in old.items() if k not in ("recorded", "digest")} == outcome:
        return False
    item["outcome"] = outcome | {"recorded": date.today().isoformat()}
    item_path.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
    return True
