"""Rule-based ranking of items not yet covered by a digest.

Location only adds points, so a citywide item with no address can still rank
on topic alone.
"""

import json
from pathlib import Path

import yaml

from lacomm.geo import Neighborhoods
from lacomm.store import DATA

INTERESTS = DATA.parent / "config" / "interests.yaml"


def load_interests(path: Path = INTERESTS) -> dict:
    return yaml.safe_load(path.read_text())


def score_item(item: dict, interests: dict, hoods: Neighborhoods) -> tuple[int, list[str]]:
    points, reasons = 0, []
    for topic in item.get("topics", []):
        if weight := interests["topics"].get(topic):
            points += weight
            reasons.append(topic)

    watched = interests["neighborhoods"]
    inside = {loc["neighborhood"] for loc in item.get("locations", []) if loc.get("neighborhood") in watched}
    near = set()
    for loc in item.get("locations", []):
        if "lat" in loc:
            near |= set(hoods.nearby(loc["lat"], loc["lon"], watched, interests["nearby_km"]))
    if inside:
        points += interests["in_neighborhood"]
        reasons.append("in " + ", ".join(sorted(inside)))
    elif near:
        points += interests["nearby"]
        reasons.append("near " + ", ".join(sorted(near)))
    return points, reasons


def candidates(root: Path = DATA, interests: dict | None = None) -> list[dict]:
    """Extracted items not yet in a digest, highest score first."""
    interests = interests or load_interests()
    hoods = Neighborhoods()
    ranked = []
    for path in sorted((root / "items").rglob("*.json")):
        item = json.loads(path.read_text())
        if "summary" not in item or "digest" in item:
            continue
        points, reasons = score_item(item, interests, hoods)
        ranked.append({"score": points, "reasons": reasons, "path": str(path.relative_to(root.parent)), **item})
    ranked.sort(key=lambda c: c["meeting_date"], reverse=True)
    ranked.sort(key=lambda c: c["score"], reverse=True)  # stable: newest first within a score
    return ranked
