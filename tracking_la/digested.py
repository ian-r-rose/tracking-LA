"""Which digest covered each item and each decision, kept apart from the item files so
they record only what the sources said (and what extraction made of it).

data/digested.csv has a row per item (decision_recorded empty) and a row per decision
on an item (its outcome's `recorded` date, so a later decision on the same item is new).
"""

import csv
from pathlib import Path

from tracking_la.store import DATA

DIGESTED = DATA / "digested.csv"
FIELDS = ("digest", "item_id", "decision_recorded")


def load(path: Path = DIGESTED) -> dict[tuple[str, str], str]:
    """{(item id, decision recorded date or ""): digest date}"""
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        return {(row["item_id"], row["decision_recorded"]): row["digest"] for row in csv.DictReader(f)}


def append(rows: list[tuple[str, str, str]], path: Path = DIGESTED) -> None:
    """Add (digest, item id, decision recorded date or "") rows."""
    new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        if new:
            writer.writerow(FIELDS)
        writer.writerows(rows)
