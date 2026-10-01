import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# Fields owned by the scraper. Everything else (summary, topics, locations, details, flag)
# is added by later stages and must survive a re-fetch.
SOURCE_FIELDS = ("id", "commission", "meeting_date", "item_number", "title", "text", "urls")


def item_path(item: dict, root: Path = DATA) -> Path:
    return root / "items" / item["commission"] / item["meeting_date"][:4] / f"{item['id']}.json"


def upsert_item(item: dict, root: Path = DATA) -> str:
    """Write an item, keeping fields from later stages. Returns 'new', 'updated' or 'unchanged'."""
    path = item_path(item, root)
    existing = json.loads(path.read_text()) if path.exists() else None
    merged = {**(existing or {}), **{k: item[k] for k in SOURCE_FIELDS}}
    if merged == existing:
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return "updated" if existing else "new"
