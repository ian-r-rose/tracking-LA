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
