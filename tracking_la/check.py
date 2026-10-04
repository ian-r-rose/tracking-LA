"""Validate item files after LLM extraction.

Catches what the extraction agents get wrong: invalid JSON, missing or malformed
fields, topics outside the fixed vocabulary, and edits to scraper-owned fields
(compared against the last commit).
"""

import json
import subprocess
from pathlib import Path

from tracking_la.store import DATA, SOURCE_FIELDS

OUTCOME_STATUSES = {"approved", "denied", "continued", "withdrawn", "filed", "other"}
TOPICS = {"parks", "transportation", "land_use", "housing", "environment", "budget", "public_safety", "other"}


def committed_version(path: Path) -> dict | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path.relative_to(DATA.parent)}"],
        cwd=DATA.parent, capture_output=True, text=True,
    )
    return json.loads(result.stdout) if result.returncode == 0 else None


def check_item(path: Path) -> list[str]:
    try:
        item = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]

    problems = []
    if "summary" in item:  # extracted; validate the extraction fields
        if not isinstance(item["summary"], str) or not item["summary"].strip():
            problems.append("summary must be a non-empty string")
        topics = item.get("topics")
        if not isinstance(topics, list) or not topics or not set(topics) <= TOPICS:
            problems.append(f"topics must be a non-empty subset of {sorted(TOPICS)}, got {topics!r}")
        locations = item.get("locations")
        if not isinstance(locations, list) or not all(isinstance(l, dict) and l.get("text") for l in locations):
            problems.append("locations must be a list of objects with a 'text' field")
        if not isinstance(item.get("details", {}), dict):
            problems.append("details must be an object")

    if (outcome := item.get("outcome")) is not None:
        if outcome.get("status") not in OUTCOME_STATUSES or not outcome.get("text") or not outcome.get("source"):
            problems.append(f"outcome needs status in {sorted(OUTCOME_STATUSES)}, text and source: {outcome!r}")

    if committed := committed_version(path):
        changed = [k for k in SOURCE_FIELDS if item.get(k) != committed.get(k)]
        if changed:
            problems.append(f"scraper-owned fields were modified: {changed}")
    return problems


def check_all(root: Path = DATA) -> int:
    """Print problems for every item file; return the number of bad files."""
    bad = 0
    for path in sorted((root / "items").rglob("*.json")):
        if problems := check_item(path):
            bad += 1
            print(f"{path.relative_to(root.parent)}:")
            for problem in problems:
                print(f"  - {problem}")
    return bad
