"""Authoritative Planetary Computer STAC access for GeoFM admission and work."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from functools import lru_cache

import planetary_computer
from pystac import Item
from pystac_client import Client

from .jobs import ImageryObservation, RunError

DEFAULT_STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
SUPPORTED_COLLECTIONS = ("hls2-s30", "hls2-l30")


class StacItemSummary:
    """Reduced metadata needed while producing result manifests."""

    def __init__(
        self,
        *,
        item_id: str,
        collection: str,
        acquired_at: datetime,
        geometry: dict,
        bbox: tuple[float, float, float, float],
    ) -> None:
        self.item_id = item_id
        self.collection = collection
        self.acquired_at = acquired_at
        self.geometry = geometry
        self.bbox = bbox


class PlanetaryComputerCatalog:
    """Public Planetary Computer adapter used behind the MCP service."""

    def __init__(self, endpoint: str = DEFAULT_STAC_API) -> None:
        self._client = Client.open(endpoint)

    def get_asset_inventory(self, item_id: str) -> ImageryObservation:
        """Return unsigned metadata used to admit a model run."""
        item = self._get_item(item_id)
        acquired_at = _acquired_at(item)
        if item.geometry is None or item.collection_id is None:
            raise RunError(f"STAC item '{item.id}' is missing spatial metadata.")
        properties = item.properties
        tile_id = (
            properties.get("s2:mgrs_tile")
            or properties.get("hls:tile_id")
            or properties.get("mgrs:tile")
            or _tile_from_item_id(item.id)
        )
        return ImageryObservation(
            item_id=item.id,
            collection=item.collection_id,
            asset_keys=frozenset(item.assets),
            resolution_m=_extract_resolution_m(item),
            acquired_at=acquired_at,
            tile_id=str(tile_id) if tile_id else None,
            geometry=item.geometry,
        )

    def get_item_summary(self, item_id: str) -> StacItemSummary:
        """Return bounded source metadata for an evidence manifest."""
        item = self._get_item(item_id)
        if item.geometry is None or item.bbox is None or item.collection_id is None:
            raise RunError(f"STAC item '{item.id}' is missing required spatial metadata.")
        return StacItemSummary(
            item_id=item.id,
            collection=item.collection_id,
            acquired_at=_acquired_at(item),
            geometry=item.geometry,
            bbox=tuple(item.bbox),
        )

    def get_signed_assets(self, item_id: str, asset_keys: tuple[str, ...]) -> dict[str, str]:
        """Sign only the explicitly requested source assets."""
        signed = planetary_computer.sign(self._get_item(item_id))
        return {
            key: signed.assets[key].href
            for key in asset_keys
            if key in signed.assets and signed.assets[key].href
        }

    def _get_item(self, item_id: str) -> Item:
        item = next(
            self._client.search(
                ids=[item_id],
                collections=list(SUPPORTED_COLLECTIONS),
                max_items=1,
            ).items(),
            None,
        )
        if item is None:
            raise RunError(f"STAC item '{item_id}' was not found in an approved HLS collection.")
        return item


@lru_cache(maxsize=1)
def get_catalog() -> PlanetaryComputerCatalog:
    """Return the process-local catalogue client."""
    return PlanetaryComputerCatalog(os.getenv("PUBLIC_STAC_API", DEFAULT_STAC_API))


def _acquired_at(item: Item) -> datetime:
    acquired_at = item.datetime
    if acquired_at is None:
        raise RunError(f"STAC item '{item.id}' has no acquisition datetime.")
    return acquired_at if acquired_at.tzinfo else acquired_at.replace(tzinfo=UTC)


def _extract_resolution_m(item: Item) -> float:
    candidates: list[float] = []

    def add_metadata(metadata: dict) -> None:
        if metadata.get("gsd") is not None:
            candidates.append(float(metadata["gsd"]))
        projection = metadata.get("proj:transform")
        if isinstance(projection, list) and len(projection) >= 6:
            width = math.hypot(float(projection[0]), float(projection[3]))
            height = math.hypot(float(projection[1]), float(projection[4]))
            if not math.isclose(width, height, rel_tol=0.001, abs_tol=0.01):
                raise RunError(
                    f"STAC item '{item.id}' has non-square pixels ({width:g} by {height:g})."
                )
            candidates.append(width)

    add_metadata(item.properties)
    for asset in item.assets.values():
        add_metadata(asset.extra_fields)
    if not candidates:
        raise RunError(
            f"STAC item '{item.id}' has no ground sample distance or projection transform."
        )
    reference = candidates[0]
    if any(
        not math.isclose(reference, candidate, rel_tol=0.001, abs_tol=0.01)
        for candidate in candidates[1:]
    ):
        raise RunError(f"STAC item '{item.id}' has conflicting resolutions.")
    return reference


def _tile_from_item_id(item_id: str) -> str | None:
    parts = item_id.split(".")
    return next((part[1:] for part in parts if part.startswith("T") and len(part) == 6), None)