"""Precomputed Canadian 2026 STAC examples used by the Get Started UI."""

from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


QUICKSTART_QUERIES: dict[str, dict[str, Any]] = {
    "show sentinel-2 imagery over toronto, canada from 2026-06-01 to 2026-08-26": {
        "collections": ["sentinel-2-l2a"],
        "location": "Toronto, Ontario, Canada",
        "bbox": [-79.64, 43.58, -79.12, 43.86],
        "description": "10m surface-reflectance imagery for Greater Toronto",
        "dataset": "Sentinel-2 L2A",
        "intent": "stac",
        "temporal": "2026-06-01/2026-08-26",
    },
    "show hls imagery over calgary, canada from 2026-05-01 to 2026-08-26": {
        "collections": ["hls2-s30"],
        "location": "Calgary, Alberta, Canada",
        "bbox": [-114.32, 50.84, -113.83, 51.21],
        "description": "30m harmonized Sentinel-2 imagery over Calgary",
        "dataset": "HLS S30",
        "intent": "stac",
        "temporal": "2026-05-01/2026-08-26",
    },
    "show landsat imagery over halifax, canada from 2026-01-01 to 2026-08-26": {
        "collections": ["landsat-c2-l2"],
        "location": "Halifax, Nova Scotia, Canada",
        "bbox": [-63.85, 44.48, -63.35, 44.82],
        "description": "Landsat surface reflectance over coastal Nova Scotia",
        "dataset": "Landsat C2 L2",
        "intent": "stac",
        "temporal": "2026-01-01/2026-08-26",
    },
    "show modis thermal anomalies across alberta from 2026-05-01 to 2026-08-26": {
        "collections": ["modis-14A1-061"],
        "location": "Alberta, Canada",
        "bbox": [-120.0, 49.0, -110.0, 60.0],
        "description": "Daily active-fire and thermal-anomaly observations",
        "dataset": "MODIS 14A1",
        "intent": "stac",
        "temporal": "2026-05-01/2026-08-26",
    },
    "show modis vegetation indices over saskatchewan from 2026-04-01 to 2026-08-26": {
        "collections": ["modis-13Q1-061"],
        "location": "Saskatchewan, Canada",
        "bbox": [-110.0, 49.0, -101.36, 60.0],
        "description": "250m NDVI and EVI composites over Prairie cropland",
        "dataset": "MODIS 13Q1",
        "intent": "stac",
        "temporal": "2026-04-01/2026-08-26",
    },
    "show modis gross primary productivity over british columbia from 2026-05-01 to 2026-08-26": {
        "collections": ["modis-17A2H-061"],
        "location": "British Columbia, Canada",
        "bbox": [-139.06, 48.30, -114.03, 60.0],
        "description": "8-day vegetation productivity composites",
        "dataset": "MODIS 17A2H",
        "intent": "stac",
        "temporal": "2026-05-01/2026-08-26",
    },
    "show modis daily snow cover over quebec from 2026-02-01 to 2026-02-28": {
        "collections": ["modis-10A1-061"],
        "location": "Quebec, Canada",
        "bbox": [-79.76, 44.99, -57.10, 62.59],
        "description": "500m daily snow cover and NDSI",
        "dataset": "MODIS 10A1",
        "intent": "stac",
        "temporal": "2026-02-01/2026-02-28",
    },
    "show sentinel-2 imagery along the mackenzie river in canada from 2026-05-01 to 2026-06-30": {
        "collections": ["sentinel-2-l2a"],
        "location": "Mackenzie River, Northwest Territories, Canada",
        "bbox": [-136.0, 61.0, -118.0, 69.7],
        "description": "10m spring river and ice observations",
        "dataset": "Sentinel-2 L2A",
        "intent": "stac",
        "temporal": "2026-05-01/2026-06-30",
    },
    "show landsat imagery of hudson bay, canada from 2026-06-01 to 2026-08-26": {
        "collections": ["landsat-c2-l2"],
        "location": "Hudson Bay, Canada",
        "bbox": [-95.0, 50.0, -75.0, 64.0],
        "description": "30m summer coastal and sea-ice observations",
        "dataset": "Landsat C2 L2",
        "intent": "stac",
        "temporal": "2026-06-01/2026-08-26",
    },
    "show copernicus dem terrain around banff, canada for 2026 analysis": {
        "collections": ["cop-dem-glo-30"],
        "location": "Banff, Alberta, Canada",
        "bbox": [-115.80, 51.05, -115.35, 51.40],
        "description": "30m terrain elevation for current-year analysis",
        "dataset": "COP-DEM GLO-30",
        "intent": "stac",
    },
    "show sentinel-1 rtc radar imagery over vancouver, canada from 2026-01-01 to 2026-08-26": {
        "collections": ["sentinel-1-rtc"],
        "location": "Vancouver, British Columbia, Canada",
        "bbox": [-123.40, 49.0, -122.70, 49.40],
        "description": "10m terrain-corrected radar backscatter",
        "dataset": "Sentinel-1 RTC",
        "intent": "stac",
        "temporal": "2026-01-01/2026-08-26",
    },
    "show sentinel-1 rtc radar imagery over the red river, manitoba from 2026-03-01 to 2026-05-31": {
        "collections": ["sentinel-1-rtc"],
        "location": "Red River, Manitoba, Canada",
        "bbox": [-97.45, 49.0, -96.70, 50.20],
        "description": "All-weather spring flood observations",
        "dataset": "Sentinel-1 RTC",
        "intent": "stac",
        "temporal": "2026-03-01/2026-05-31",
    },
}


def normalize_query(query: str) -> str:
    """Normalize a query for exact matching."""
    return query.casefold().strip()


def is_quickstart_query(query: str) -> bool:
    """Return whether a query is a fully specified Canadian example."""
    return normalize_query(query) in QUICKSTART_QUERIES


def get_quickstart_classification(query: str) -> dict[str, Any] | None:
    """Return the precomputed router classification for a known example."""
    quickstart = QUICKSTART_QUERIES.get(normalize_query(query))
    if quickstart is None:
        return None
    return {
        "is_quickstart": True,
        "intent": quickstart.get("intent", "stac"),
        "intent_type": quickstart.get("intent", "stac"),
        "collections": quickstart.get("collections", []),
        "has_location": True,
        "has_temporal": "temporal" in quickstart,
        "data_type": "satellite_imagery",
        "confidence": 1.0,
        "router_action": None,
        "description": quickstart.get("description", ""),
        "dataset": quickstart.get("dataset", ""),
        "needs_satellite_data": True,
        "needs_contextual_info": False,
        "needs_vision_analysis": False,
    }


def get_quickstart_location(query: str) -> dict[str, Any] | None:
    """Return the precomputed Canadian location and STAC constraints."""
    quickstart = QUICKSTART_QUERIES.get(normalize_query(query))
    if quickstart is None:
        return None
    return {
        "location": quickstart.get("location", ""),
        "bbox": quickstart.get("bbox", []),
        "collections": quickstart.get("collections", []),
        "temporal": quickstart.get("temporal"),
        "description": quickstart.get("description", ""),
        "dataset": quickstart.get("dataset", ""),
    }


def get_quickstart_stats() -> dict[str, Any]:
    """Return cache statistics for startup telemetry."""
    collections = {
        collection
        for query_data in QUICKSTART_QUERIES.values()
        for collection in query_data.get("collections", [])
    }
    return {
        "total_queries": len(QUICKSTART_QUERIES),
        "collections_covered": sorted(collections),
        "intents": ["stac"],
        "locations": [query.get("location", "") for query in QUICKSTART_QUERIES.values()],
    }


def get_all_quickstart_queries() -> list[str]:
    """Return all normalized Canadian quick-start query strings."""
    return list(QUICKSTART_QUERIES)


logger.info(
    "[LAUNCH] Quick Start Cache initialized with %d pre-computed queries",
    len(QUICKSTART_QUERIES),
)