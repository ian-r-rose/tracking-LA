"""Geocode item locations and place them in neighborhoods.

Geocoding uses the City of LA's ArcGIS locator (built on City street centerlines).
It's undocumented, so we go easy on it: every query is cached in geo/geocode-cache.json
and only new queries hit the network.
"""

import json
import math
import os
import re
from pathlib import Path

import httpx
from shapely.geometry import Point, shape
from shapely.ops import transform

GEO = Path(__file__).resolve().parent.parent / "geo"
CACHE = GEO / "geocode-cache.json"
LOCATOR = (
    "https://maps.lacity.org/arcgis/rest/services/Locators/"
    "centerlineLocatorArcPro/GeocodeServer/findAddressCandidates"
)
MIN_SCORE = 85

# Set LACOMM_CONTACT (an email or URL) so the City can reach us about our traffic.
USER_AGENT = "la-commissions/0.1" + (f" ({c})" if (c := os.environ.get("LACOMM_CONTACT")) else "")


def clean_query(text: str) -> str:
    """The City locator only covers LA and scores worse with a city/state suffix."""
    return re.sub(r",?\s*(Los Angeles,?\s*)?(CA|California)(\s+\d{5})?\s*$", "", text, flags=re.IGNORECASE).strip()


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
        return hit if hit and hit["score"] >= MIN_SCORE else None

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
