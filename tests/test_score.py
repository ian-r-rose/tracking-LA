from lacomm.geo import Neighborhoods
from lacomm.score import score_item

INTERESTS = {
    "topics": {"parks": 3, "transportation": 3, "land_use": 1},
    "neighborhoods": ["Westlake", "Highland Park"],
    "in_neighborhood": 4,
    "nearby": 2,
    "nearby_km": 1.0,
}
HOODS = Neighborhoods()


def test_park_in_watched_neighborhood_scores_topic_plus_location():
    item = {"topics": ["parks", "land_use"], "locations": [{"text": "MacArthur Park", "lat": 34.0577, "lon": -118.2784, "neighborhood": "Westlake"}]}
    assert score_item(item, INTERESTS, HOODS) == (8, ["parks", "land_use", "in Westlake"])


def test_nearby_scores_less_than_inside():
    # The Original Pantry is in Downtown, within 1 km of Westlake.
    item = {"topics": ["land_use"], "locations": [{"text": "873 S Figueroa St", "lat": 34.046575, "lon": -118.262562, "neighborhood": "Downtown"}]}
    assert score_item(item, INTERESTS, HOODS) == (3, ["land_use", "near Westlake"])


def test_citywide_item_ranks_on_topic_alone():
    item = {"topics": ["transportation"], "locations": []}
    assert score_item(item, INTERESTS, HOODS) == (3, ["transportation"])


def test_candidates_include_items_already_in_the_digest_being_rewritten(tmp_path):
    import json
    from lacomm.score import candidates

    folder = tmp_path / "items" / "x" / "2026"
    folder.mkdir(parents=True)
    for name, extra in [("new", {}), ("same", {"digest": "2026-10-05"}), ("older", {"digest": "2026-10-01"})]:
        item = {"id": name, "meeting_date": "2026-10-01", "summary": name, "topics": ["other"], "locations": [], **extra}
        (folder / f"{name}.json").write_text(json.dumps(item))
    interests = {"topics": {}, "neighborhoods": [], "in_neighborhood": 4, "nearby": 2, "nearby_km": 1}
    assert {c["id"] for c in candidates(tmp_path, interests)} == {"new"}
    assert {c["id"] for c in candidates(tmp_path, interests, "2026-10-05")} == {"new", "same"}
