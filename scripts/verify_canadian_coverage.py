"""Check Canadian public-catalog scene coverage without model calls or deployments.

Run without arguments to inspect the matrix; pass --live to query Public PC.
Coverage confirms scene footprints, not valid source pixels or analysis quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from shapely.errors import GEOSException
from shapely.geometry import Point, shape
from shapely.validation import make_valid


ROOT = Path(__file__).resolve().parents[1]
LOCATIONS = ROOT / "planetary-explorer/container-app/tests/fixtures/canadian_locations.json"
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
COLLECTIONS = (
    "sentinel-2-l2a", "hls2-s30", "landsat-c2-l2", "modis-14A1-061",
    "modis-13Q1-061", "modis-17A2H-061", "modis-10A1-061",
    "cop-dem-glo-30", "sentinel-1-rtc",
)


def validate_response(
    payload: dict[str, Any],
    collection: str,
    point: tuple[float, float],
    date_range: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Classify scene coverage, honest absence, or an invalid catalog response."""
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        return {"outcome": "error", "reason": "Expected a STAC FeatureCollection."}
    features = payload.get("features")
    if not isinstance(features, list):
        return {"outcome": "error", "reason": "Missing STAC features array."}
    if not features:
        return {"outcome": "no_data", "scene_id": None}

    latitude, longitude = point
    for feature in features:
        if not isinstance(feature, dict) or feature.get("collection") != collection:
            continue
        try:
            geometry = shape(feature["geometry"])
            warnings = []
            if not geometry.is_valid:
                geometry = make_valid(geometry)
                warnings.append("Catalog footprint required geometry repair; source pixels remain unverified.")
            if not geometry.is_valid or not geometry.covers(Point(longitude, latitude)):
                continue
            properties = feature.get("properties") or {}
            scene_start = properties.get("datetime") or properties.get("start_datetime")
            scene_end = properties.get("datetime") or properties.get("end_datetime")
            if date_range:
                start = datetime.fromisoformat(str(scene_start).replace("Z", "+00:00")).date()
                end = datetime.fromisoformat(str(scene_end).replace("Z", "+00:00")).date()
                if start > date.fromisoformat(date_range[1]) or end < date.fromisoformat(date_range[0]):
                    continue
            if not feature.get("id"):
                continue
            result = {
                "outcome": "covered",
                "scene_id": feature["id"],
                "scene_start": scene_start,
                "scene_end": scene_end,
            }
            if warnings:
                result["warnings"] = warnings
            return result
        except (KeyError, TypeError, ValueError, AttributeError, GEOSException):
            continue
    return {"outcome": "error", "reason": "Returned scenes do not match the point, collection, or dates."}


async def run_matrix(
    locations: list[dict[str, Any]],
    collections: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Query the fixed public STAC endpoint sequentially and retain minimal provenance."""
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for location in locations:
            point = (location["latitude"], location["longitude"])
            for collection in collections:
                row = {"location": location["name"], "region": location["region"], "collection": collection}
                date_range = None if collection == "cop-dem-glo-30" else (
                    start_date.isoformat(), end_date.isoformat(),
                )
                query: dict[str, Any] = {
                    "collections": [collection],
                    "intersects": {"type": "Point", "coordinates": [point[1], point[0]]},
                    "limit": 1,
                }
                if date_range:
                    query["datetime"] = f"{date_range[0]}T00:00:00Z/{date_range[1]}T23:59:59Z"
                try:
                    response = await client.post(STAC_URL, json=query)
                    response.raise_for_status()
                    row.update(validate_response(response.json(), collection, point, date_range))
                except (httpx.HTTPError, ValueError) as error:
                    row.update(outcome="error", reason=str(error))
                results.append(row)
                print(f"{row['outcome'].upper():7} {location['name']}: {collection}")
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": "Public PC scene footprints only; source pixels, rendering, and AI analysis were not tested.",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summary": dict(Counter(row["outcome"] for row in results)),
        "results": results,
    }


def create_parser() -> argparse.ArgumentParser:
    """Create the read-only coverage check command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Query public STAC; no model calls or Azure changes.")
    parser.add_argument("--collection", action="append", choices=COLLECTIONS, help="Restrict the matrix to one or more collections.")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 6, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 8, 26))
    parser.add_argument("--output", type=Path, help="Write minimal JSON evidence without asset URLs.")
    return parser


def main() -> int:
    """Run the matrix, returning nonzero on transport or contract failures."""
    parser = create_parser()
    args = parser.parse_args()
    if args.start_date > args.end_date:
        parser.error("--start-date must be on or before --end-date")
    try:
        locations = json.loads(LOCATIONS.read_text(encoding="utf-8"))
        collections = list(dict.fromkeys(args.collection or COLLECTIONS))
        if not args.live:
            print(f"{len(locations)} Canadian points x {len(collections)} collections. Pass --live to query public STAC.")
            return 0
        report = asyncio.run(run_matrix(locations, collections, args.start_date, args.end_date))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], sort_keys=True))
        return int(bool(report["summary"].get("error")))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())