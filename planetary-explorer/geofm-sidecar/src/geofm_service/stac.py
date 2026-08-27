"""Authoritative Planetary Computer STAC access for GeoFM admission and work."""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from functools import lru_cache

import planetary_computer
from pystac import Item
from pystac_client import Client

from .jobs import ImageryObservation, RunError
from .policy import supported_collections

DEFAULT_STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
UTC = timezone.utc


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
        asset_resolutions = _extract_asset_resolutions_m(item)
        return ImageryObservation(
            item_id=item.id,
            collection=item.collection_id,
            asset_keys=frozenset(item.assets),
            resolution_m=_extract_resolution_m(item, asset_resolutions),
            asset_resolutions_m=asset_resolutions,
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
                collections=list(supported_collections()),
                max_items=1,
            ).items(),
            None,
        )
        if item is None:
            raise RunError(
                f"STAC item '{item_id}' was not found in a GeoFM-approved collection."
            )
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


def _asset_resolution_m(item_id: str, metadata: dict) -> float | None:
    """Derive one asset's square-pixel resolution from STAC metadata."""
    projection = metadata.get("proj:transform")
    if isinstance(projection, list) and len(projection) >= 6:
        width = math.hypot(float(projection[0]), float(projection[3]))
        height = math.hypot(float(projection[1]), float(projection[4]))
        if not math.isclose(width, height, rel_tol=0.001, abs_tol=0.01):
            raise RunError(
                f"STAC item '{item_id}' has non-square pixels ({width:g} by {height:g})."
            )
        return width
    if metadata.get("gsd") is not None:
        return float(metadata["gsd"])
    return None


def _extract_asset_resolutions_m(item: Item) -> dict[str, float]:
    """Return the resolution of every asset that publishes one."""
    item_level = _asset_resolution_m(item.id, item.properties)
    resolutions: dict[str, float] = {}
    for key, asset in item.assets.items():
        resolution = _asset_resolution_m(item.id, asset.extra_fields)
        if resolution is None:
            resolution = item_level
        if resolution is not None:
            resolutions[key] = resolution
    return resolutions


def _extract_resolution_m(item: Item, asset_resolutions: dict[str, float]) -> float:
    """Return the item's finest published resolution, failing closed when absent."""
    item_level = _asset_resolution_m(item.id, item.properties)
    if item_level is not None:
        return item_level
    if not asset_resolutions:
        raise RunError(
            f"STAC item '{item.id}' has no ground sample distance or projection transform."
        )
    return min(asset_resolutions.values())


def _tile_from_item_id(item_id: str) -> str | None:
    """Recover an MGRS tile from HLS, Sentinel-2 or Sentinel-1 identifier conventions."""
    for separator in (".", "_"):
        for part in item_id.split(separator):
            if part.startswith("T") and len(part) == 6 and part[1:].isalnum():
                return part[1:]
            if len(part) == 5 and part[:2].isdigit() and part[2:].isalpha():
                return part
    return None