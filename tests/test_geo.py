import httpx

from lacomm.geo import Geocoder, Neighborhoods, Places, clean_query, plausible


def test_clean_query_strips_city_and_state():
    assert clean_query("217 North Avenue 55, Los Angeles, CA") == "217 North Avenue 55"
    assert clean_query("873 S Figueroa St, Los Angeles, CA 90017") == "873 S Figueroa St"
    assert clean_query("N Figueroa St & Avenue 58") == "N Figueroa St & Avenue 58"


def test_geocoder_caches_and_rejects_low_scores(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        score = 99 if "Figueroa" in request.url.params["SingleLine"] else 60
        address = request.url.params["SingleLine"].upper()
        candidate = {"address": address, "score": score, "location": {"x": -118.26, "y": 34.05}}
        return httpx.Response(200, json={"candidates": [candidate]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        geocoder = Geocoder(client, tmp_path / "cache.json")
        assert geocoder.geocode("873 S Figueroa St, Los Angeles, CA")["lat"] == 34.05
        assert geocoder.geocode("873 S Figueroa St")["lat"] == 34.05  # same query after cleaning
        assert geocoder.geocode("1 Nowhere Ln") is None
        geocoder.save()
    assert len(requests) == 2

    reloaded = Geocoder(httpx.Client(transport=httpx.MockTransport(handler)), tmp_path / "cache.json")
    assert reloaded.geocode("873 S Figueroa St")["lat"] == 34.05
    assert len(requests) == 2


def test_neighborhood_containment_and_nearby():
    hoods = Neighborhoods()
    original_pantry = (34.04606, -118.26360)
    assert hoods.containing(*original_pantry) == "Downtown"
    # The Original Pantry is near Westlake but nowhere near Highland Park.
    assert hoods.nearby(*original_pantry, ["Westlake", "Highland Park"], km=1.0) == ["Westlake"]


def test_places_match_park_names():
    places = Places()
    lat, lon = places.lookup("Sycamore Grove Park")
    assert places.lookup("Griffith Park")
    assert Neighborhoods().containing(lat, lon) == "Highland Park"
    assert places.lookup("sycamore grove park, Los Angeles, CA") == (lat, lon)
    assert places.lookup("123 Main St") is None


def test_plausible_rejects_matches_on_the_wrong_street():
    assert plausible("Alameda St & E 18th St", "N ALAMEDA ST & E 18TH ST, 90021")
    assert not plausible("Alameda St & E 18th St", "N ALAMEDA ST & E E ST, 90744")
    assert plausible("217 North Avenue 55", "217 W AVENUE 55, 90042")
    assert plausible("2718 North Hyperion Avenue", "2718 N HYPERION AVE, 90027")
    assert not plausible("2718 North Hyperion Avenue", "2718 N HOBART BLVD, 90027")
    assert plausible("4849 North Mount Royal Drive", "4849 N MT ROYAL DR, 90041")


def test_zoo_alias():
    assert Places().lookup("LA Zoo") == Places().lookup("Los Angeles Zoo")
    assert Places().lookup("Los Angeles Zoo, 5333 Zoo Drive, Los Angeles, CA") == Places().lookup("Los Angeles Zoo")
