"""Geocode item locations and place them in neighborhoods.

Geocoding uses the City of LA's ArcGIS locator (built on City street centerlines).
It's undocumented, so we go easy on it: every query is cached in geo/geocode-cache.json
and only new queries hit the network.
"""

import json
import math
import re
from pathlib import Path

import httpx
from shapely.geometry import Point, shape
from shapely.ops import transform

from lacomm import USER_AGENT

GEO = Path(__file__).resolve().parent.parent / "geo"
CACHE = GEO / "geocode-cache.json"
LOCATOR = (
    "https://maps.lacity.org/arcgis/rest/services/Locators/"
    "centerlineLocatorArcPro/GeocodeServer/findAddressCandidates"
)
MIN_SCORE = 85


def clean_query(text: str) -> str:
    """The City locator only covers LA and scores worse with a city/state suffix."""
    return re.sub(r",?\s*(Los Angeles,?\s*)?(CA|California)(\s+\d{5})?\s*$", "", text, flags=re.IGNORECASE).strip()


_STREET_WORDS = re.compile(
    r"^(n|s|e|w|north|south|east|west|st|street|ave|avenue|blvd|boulevard|dr|drive|rd|road|pl|place|"
    r"way|ct|court|ln|lane|ter|terrace|pkwy|parkway|hwy|highway|cir|circle|the)$"
)


_ABBREVIATIONS = {"mount": "mt", "fort": "ft", "saint": "st", "junior": "jr"}


def _words(text: str) -> list[str]:
    return [_ABBREVIATIONS.get(w, w) for w in re.findall(r"[a-z0-9]+", text.lower())]


def plausible(query: str, matched: str) -> bool:
    """The locator sometimes returns a confident match on the wrong street (asked for
    "Alameda St & E 18th St", it answered "Alameda St & E E St" in Wilmington). Require every
    street-name word in the query, other than house numbers, directions and suffixes, to
    appear in the matched address."""
    matched_words = set(_words(matched))
    for part in query.split("&"):
        words = _words(part)
        if words and part is query.split("&")[0] and words[0].isdigit() and "&" not in query:
            words = words[1:]  # house number
        if not all(w in matched_words for w in words if not _STREET_WORDS.match(w)):
            return False
    return True


class Geocoder:
    def __init__(self, client: httpx.Client, cache_path: Path = CACHE):
        self.client = client
        self.cache_path = cache_path
        self.cache: dict = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        self.lookups = 0

    def geocode(self, text: str) -> dict | None:
        query = clean_query(text)
        if query not in self.cache:
            self.lookups += 1
            resp = self.client.get(
                LOCATOR,
                params={"SingleLine": query, "outSR": 4326, "maxLocations": 1, "f": "json"},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            candidates = resp.json().get("candidates", [])
            best = candidates[0] if candidates else None
            self.cache[query] = best and {
                "address": best["address"],
                "score": best["score"],
                "lat": round(best["location"]["y"], 6),
                "lon": round(best["location"]["x"], 6),
            }
        hit = self.cache[query]
        return hit if hit and hit["score"] >= MIN_SCORE and plausible(query, hit["address"]) else None

    def save(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


# Local equirectangular projection to kilometers; accurate enough across LA for "within 1 km".
_KM_PER_DEG_LAT = 110.57
_KM_PER_DEG_LON = 111.32 * math.cos(math.radians(34.05))


def _to_km(lon, lat, z=None):
    return lon * _KM_PER_DEG_LON, lat * _KM_PER_DEG_LAT


class Neighborhoods:
    def __init__(self, path: Path = GEO / "neighborhoods.geojson"):
        features = json.loads(path.read_text())["features"]
        self.shapes = {f["properties"]["name"]: transform(_to_km, shape(f["geometry"])) for f in features}

    def containing(self, lat: float, lon: float) -> str | None:
        point = Point(_to_km(lon, lat))
        return next((name for name, poly in self.shapes.items() if poly.contains(point)), None)

    def nearby(self, lat: float, lon: float, names: list[str], km: float) -> list[str]:
        """Which of `names` the point is in or within `km` of."""
        point = Point(_to_km(lon, lat))
        return [n for n in names if n in self.shapes and self.shapes[n].distance(point) <= km]


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", name.lower())).strip()


PLACES = GEO / "places.json"

# Rec & Parks layers on LA GeoHub: park boundaries first (Griffith Park, Venice Beach),
# then facilities (recreation centers, pools, senior centers), which fill in names
# the first layer lacks.
PLACE_LAYERS = [
    "https://maps.lacity.org/lahub/rest/services/Recreation_and_Parks_Department/MapServer/5/query",
    "https://services5.arcgis.com/7nsPwEMP38bSkCjy/arcgis/rest/services/"
    "Los_Angeles_City_Recreation_and_Parks_Facility_Boundaries/FeatureServer/0/query",
]


def build_places(client: httpx.Client, path: Path = PLACES) -> int:
    """Download named Rec & Parks sites and save one representative point per name."""
    points: dict[str, list[float]] = {}
    for url in PLACE_LAYERS:
        resp = client.get(url, params={"where": "1=1", "outFields": "Name", "outSR": 4326, "f": "geojson"})
        resp.raise_for_status()
        for feature in resp.json()["features"]:
            name = (feature["properties"].get("Name") or "").strip()
            if name and feature["geometry"] and _normalize_name(name) not in points:
                point = shape(feature["geometry"]).representative_point()
                points[_normalize_name(name)] = [round(point.y, 6), round(point.x, 6)]
    path.write_text(json.dumps(points, indent=0, sort_keys=True) + "\n")
    return len(points)


class Places:
    """Named Rec & Parks sites, for locations given as a name rather than an address."""

    def __init__(self, path: Path = PLACES):
        self.points = json.loads(path.read_text()) if path.exists() else {}

    def lookup(self, text: str) -> tuple[float, float] | None:
        point = self.points.get(_normalize_name(clean_query(text)))
        return tuple(point) if point else None
