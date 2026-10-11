import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# Fields owned by the scraper. Everything else (summary, topics, locations, details, flag)
# is added by later stages and must survive a re-fetch.
SOURCE_FIELDS = ("id", "body", "meeting_date", "item_number", "title", "text", "urls", "follows")

# Extraction an item takes from the earlier item it `follows` (a full Council item, from
# the committee item on the same Council File), instead of being extracted again.
CARRIED_FIELDS = ("summary", "topics", "locations", "details")


def item_path(item: dict, root: Path = DATA) -> Path:
    return root / "items" / item["body"] / item["meeting_date"][:4] / f"{item['id']}.json"


def upsert_item(item: dict, root: Path = DATA) -> str:
    """Write an item, keeping fields from later stages. Returns 'new', 'updated' or 'unchanged'."""
    path = item_path(item, root)
    existing = json.loads(path.read_text()) if path.exists() else None
    merged = carry_over({**(existing or {}), **{k: item[k] for k in SOURCE_FIELDS if k in item}}, root)
    if merged == existing:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return "updated" if existing else "new"


def carry_over(item: dict, root: Path = DATA) -> dict:
    """The item with the extraction of the item it follows, once that one is extracted."""
    if "summary" not in item and (earlier := followed_item(item, root)) and "summary" in earlier:
        return item | {k: earlier[k] for k in CARRIED_FIELDS if k in earlier}
    return item


def followed_item(item: dict, root: Path = DATA) -> dict | None:
    if not (item_id := item.get("follows")):
        return None
    path = next((root / "items").glob(f"*/*/{item_id}.json"), None)
    return json.loads(path.read_text()) if path else None
