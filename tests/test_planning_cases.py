from datetime import date
from pathlib import Path

from tracking_la.sources import planning_cases

FEED = (Path(__file__).parent / "fixtures" / "planning_cases" / "newcases.json").read_bytes()
MEETING = {"body": "planning-cases", "date": date(2026, 10, 3), "agenda_url": planning_cases.FEED}


def test_cases_for_one_project_become_one_item():
    items = {i["id"]: i for _, i in planning_cases.project_items(FEED)}
    wilshire = items["plncase-ZA-2026-5125-ZV"]  # filed with ENV-2026-5126-EAF
    assert "plncase-ENV-2026-5126-EAF" not in items
    assert wilshire["text"].splitlines()[1] == "Case numbers: ZA-2026-5125-ZV, ENV-2026-5126-EAF"
    assert wilshire["meeting_date"] == "2026-10-02"
    assert wilshire["urls"][0].endswith("/ZA-2026-5125-ZV")
    assert len(items) < 76 and all(len(i["title"]) <= 160 for i in items.values())


def test_only_projects_near_watched_neighborhoods_are_kept():
    from tracking_la.geo import Neighborhoods

    class Geocoder:
        def geocode(self, text):
            return {"1600 W SUNSET BLVD, Los Angeles, CA": {"lat": 34.0775, "lon": -118.2597}}.get(text)  # Echo Park

    interests = {"neighborhoods": ["Echo Park"], "nearby_km": 1.0}
    hoods, geocoder = Neighborhoods(), Geocoder()
    assert planning_cases.is_local("1600 W SUNSET BLVD", geocoder, hoods, interests)
    assert planning_cases.is_local("NO SUCH PLACE", geocoder, hoods, interests)  # unresolved: kept
    geocoder.geocode = lambda text: {"lat": 34.2, "lon": -118.45}  # Van Nuys
    assert not planning_cases.is_local("5601 N SEPULVEDA BLVD", geocoder, hoods, interests)


def test_case_page_outcome():
    fixtures = Path(__file__).parent / "fixtures" / "planning_cases"
    decided = (fixtures / "case-ZA-2023-5864-ZAD-HCA.html").read_text()
    assert planning_cases.case_outcome(decided, "u") == {
        "status": "approved",
        "text": "ZA action: PARTIALLY APPROVED (Sep 24, 2026); appeal period ends 10/09/2026",
        "source": "u",
    }
    assert planning_cases.case_outcome((fixtures / "case-ZA-2026-5125-ZV.html").read_text(), "u") is None
