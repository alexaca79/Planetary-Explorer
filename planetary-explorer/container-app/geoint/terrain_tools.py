"""
Terrain Analysis Tools for Azure AI Agent Service

Standalone functions compatible with Azure AI Agent Service FunctionTool.

Each function uses docstring-based parameter descriptions (the format
FunctionTool expects) and returns JSON-serializable results.

Usage:
    from geoint.terrain_tools import create_terrain_functions
    functions = create_terrain_functions()  # Returns Set[Callable]
    tool = FunctionTool(functions)
"""

import logging
import json
from typing import Dict, Any, List, Optional, Set, Callable, Tuple

import numpy as np
from cloud_config import cloud_cfg
from geoint.dem_geometry import pixel_spacing_meters, slope_aspect_degrees
from geoint.raster_mosaic import MosaicWindow, read_bbox_mosaic

logger = logging.getLogger(__name__)

# Module-level STAC catalog (lazy-loaded)
_catalog = None
_stac_endpoint = cloud_cfg.stac_catalog_url

_DEM_COLLECTION = "cop-dem-glo-30"
_DEM_SOURCE = "Copernicus DEM GLO-30"
_MAX_SOURCE_TILES = 16


def _get_catalog():
    """Lazy-load STAC catalog."""
    global _catalog
    if _catalog is None:
        from pystac_client import Client
        _catalog = Client.open(_stac_endpoint)
    return _catalog


def _calculate_bbox(latitude: float, longitude: float, radius_km: float) -> List[float]:
    """Calculate bounding box from center and radius."""
    lat_deg_per_km = 1 / 111.0
    lon_deg_per_km = 1 / (111.0 * np.cos(np.radians(latitude)))
    
    lat_delta = radius_km * lat_deg_per_km
    lon_delta = radius_km * lon_deg_per_km
    
    return [
        longitude - lon_delta,
        latitude - lat_delta,
        longitude + lon_delta,
        latitude + lat_delta
    ]


def _search_items(collection: str, bbox: List[float]) -> list:
    """Return every catalog item intersecting ``bbox`` in one bounded request."""
    search = _get_catalog().search(
        collections=[collection],
        bbox=bbox,
        limit=_MAX_SOURCE_TILES,
        max_items=_MAX_SOURCE_TILES,
    )
    return list(search.items())


def _product_period(item: Any) -> str:
    properties = getattr(item, "properties", None) or {}
    start = properties.get("start_datetime")
    if start:
        return str(start)
    moment = getattr(item, "datetime", None)
    return moment.isoformat() if moment else ""


def _latest_product_items(items: list) -> list:
    """Keep tiles from the newest product period, e.g. WorldCover 2021 over 2020."""
    if not items:
        return []
    latest = max(_product_period(item) for item in items)
    return [item for item in items if _product_period(item) == latest]


def _temporal_coverage(items: list) -> Optional[str]:
    """Return the ``start/end`` dates observed by the source items."""
    starts: List[str] = []
    ends: List[str] = []
    for item in items:
        properties = getattr(item, "properties", None) or {}
        start = properties.get("start_datetime")
        end = properties.get("end_datetime")
        if start and end:
            starts.append(str(start)[:10])
            ends.append(str(end)[:10])
        elif getattr(item, "datetime", None):
            day = item.datetime.date().isoformat()
            starts.append(day)
            ends.append(day)
    if not starts:
        return None
    return f"{min(starts)}/{max(ends)}"


def _jrc_source_label(items: list) -> str:
    """Name JRC Global Surface Water with the years its items actually observe."""
    coverage = _temporal_coverage(items)
    if not coverage:
        return "JRC Global Surface Water"
    start, end = coverage.split("/")
    return f"JRC Global Surface Water ({start[:4]}-{end[:4]})"


def _read_items_mosaic(
    items: list,
    asset: str,
    bbox: List[float],
    *,
    categorical: bool,
) -> Tuple[list, MosaicWindow]:
    """Mosaic ``asset`` from every item over ``bbox``; return the items read."""
    import planetary_computer

    used = [item for item in _latest_product_items(items) if asset in item.assets]
    if not used:
        raise ValueError(f"No '{asset}' asset in the matching source items")
    hrefs = [planetary_computer.sign(item).assets[asset].href for item in used]
    return used, read_bbox_mosaic(hrefs, bbox, categorical=categorical)


def _cell_spacing(window: MosaicWindow, latitude: float) -> Tuple[float, float]:
    return pixel_spacing_meters(*window.resolution, latitude, geographic=window.geographic)


def _read_dem(bbox: List[float], latitude: float) -> Tuple[list, MosaicWindow, Tuple[float, float]]:
    """Read a Copernicus DEM mosaic over ``bbox``; raise LookupError when absent."""
    items = _search_items(_DEM_COLLECTION, bbox)
    if not items:
        raise LookupError("No DEM data available for this location")
    used, window = _read_items_mosaic(items, "data", bbox, categorical=False)
    return used, window, _cell_spacing(window, latitude)


def _source_provenance(
    data_source: str,
    items: list,
    bbox: List[float],
    window: MosaicWindow,
    valid_pixels: int,
    *,
    spacing: Optional[Tuple[float, float]] = None,
    include_period: bool = False,
) -> Dict[str, Any]:
    """Describe the sources, extent, and coverage behind a measurement."""
    result: Dict[str, Any] = {
        "data_source": data_source,
        "source_item_ids": [item.id for item in items],
        "analysis_bbox": [round(value, 5) for value in bbox],
        "coverage_percent": round(window.coverage_percent, 1),
        "valid_pixel_count": valid_pixels,
    }
    if include_period:
        period = _temporal_coverage(items)
        if period:
            result["temporal_coverage"] = period
    if spacing is not None:
        result["cell_spacing_meters"] = {
            "north_south": round(float(spacing[0]), 1),
            "east_west": round(float(spacing[1]), 1),
        }
    if window.decimation > 1:
        result["decimation_factor"] = window.decimation
    return result


def _dem_surface(bbox: List[float], latitude: float):
    """Return ``(items, window, spacing, error)`` for slope-style DEM analysis."""
    items, window, spacing = _read_dem(bbox, latitude)
    if window.data.shape[0] < 2 or window.data.shape[1] < 2:
        return items, window, spacing, "Area too small for DEM analysis"
    return items, window, spacing, None


def get_elevation_analysis(latitude: float, longitude: float, radius_km: float = 5.0) -> str:
    """Analyze elevation data for a location. Returns min, max, mean elevation in meters, 
    elevation range, and terrain classification (flat, hilly, mountainous).
    Use this when the user asks about elevation, altitude, height, or topography.
    
    :param latitude: Center latitude of the area to analyze
    :param longitude: Center longitude of the area to analyze
    :param radius_km: Radius in kilometers for analysis area (default 5.0)
    :return: JSON string with elevation statistics and terrain classification
    """
    try:
        logger.info(f"[TOOL] get_elevation_analysis at ({latitude:.4f}, {longitude:.4f}), radius={radius_km}km")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items, window, spacing = _read_dem(bbox, latitude)
        elevation = window.data[window.valid_mask]
        if elevation.size == 0:
            return json.dumps({"error": "No valid elevation data"})
        
        elev_min = float(elevation.min())
        elev_max = float(elevation.max())
        elev_mean = float(elevation.mean())
        elev_range = elev_max - elev_min
        
        if elev_range < 50:
            terrain_type = "flat plains"
        elif elev_range < 200:
            terrain_type = "gently rolling hills"
        elif elev_range < 500:
            terrain_type = "hilly terrain"
        elif elev_range < 1000:
            terrain_type = "rugged hills"
        else:
            terrain_type = "mountainous terrain"
        
        result = {
            "elevation_min_meters": round(elev_min, 1),
            "elevation_max_meters": round(elev_max, 1),
            "elevation_mean_meters": round(elev_mean, 1),
            "elevation_range_meters": round(elev_range, 1),
            "terrain_type": terrain_type,
            **_source_provenance(_DEM_SOURCE, items, bbox, window, int(elevation.size), spacing=spacing),
        }
        
        logger.info(f"[TOOL] Elevation: {elev_min:.0f}m - {elev_max:.0f}m, type: {terrain_type}")
        return json.dumps(result)
            
    except LookupError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error(f"[TOOL] Elevation analysis failed: {e}")
        return json.dumps({"error": str(e)})


def get_slope_analysis(latitude: float, longitude: float, radius_km: float = 5.0) -> str:
    """Analyze terrain slope (steepness) for a location. Returns min, max, mean slope 
    in degrees, percentage of flat/moderate/steep areas, and traversability assessment.
    Use this when user asks about slope, steepness, gradient, or terrain difficulty.
    
    :param latitude: Center latitude of the area to analyze
    :param longitude: Center longitude of the area to analyze
    :param radius_km: Radius in kilometers for analysis area (default 5.0)
    :return: JSON string with slope statistics and traversability
    """
    try:
        logger.info(f"[TOOL] get_slope_analysis at ({latitude:.4f}, {longitude:.4f})")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items, window, spacing, error = _dem_surface(bbox, latitude)
        if error:
            return json.dumps({"error": error})
        slope, _ = slope_aspect_degrees(window.data, *spacing)
        slope = slope[np.isfinite(slope)]
        if slope.size == 0:
            return json.dumps({"error": "No valid elevation data"})
        
        slope_min = float(np.min(slope))
        slope_max = float(np.max(slope))
        slope_mean = float(np.mean(slope))
        
        flat_pct = float(np.sum(slope < 5) / slope.size * 100)
        moderate_pct = float(np.sum((slope >= 5) & (slope < 15)) / slope.size * 100)
        steep_pct = float(np.sum(slope >= 15) / slope.size * 100)
        
        result = {
            "slope_min_degrees": round(slope_min, 1),
            "slope_max_degrees": round(slope_max, 1),
            "slope_mean_degrees": round(slope_mean, 1),
            "flat_area_percent": round(flat_pct, 1),
            "moderate_slope_percent": round(moderate_pct, 1),
            "steep_area_percent": round(steep_pct, 1),
            "traversability": "easy" if slope_mean < 5 else "moderate" if slope_mean < 15 else "difficult",
            **_source_provenance(_DEM_SOURCE, items, bbox, window, int(slope.size), spacing=spacing),
        }
        
        logger.info(f"[TOOL] Slope: mean {slope_mean:.1f} deg, {flat_pct:.0f}% flat")
        return json.dumps(result)
            
    except LookupError:
        return json.dumps({"error": "No DEM data available"})
    except Exception as e:
        logger.error(f"[TOOL] Slope analysis failed: {e}")
        return json.dumps({"error": str(e)})


def get_aspect_analysis(latitude: float, longitude: float, radius_km: float = 5.0) -> str:
    """Analyze terrain aspect (slope direction/facing). Returns dominant direction 
    (N, NE, E, etc), direction distribution, and sun exposure assessment.
    Use this when user asks about which way slopes face, sun exposure, or orientation.
    
    :param latitude: Center latitude of the area to analyze
    :param longitude: Center longitude of the area to analyze
    :param radius_km: Radius in kilometers for analysis area (default 5.0)
    :return: JSON string with aspect direction and sun exposure
    """
    try:
        logger.info(f"[TOOL] get_aspect_analysis at ({latitude:.4f}, {longitude:.4f})")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items, window, spacing, error = _dem_surface(bbox, latitude)
        if error:
            return json.dumps({"error": error})
        slope, aspect = slope_aspect_degrees(window.data, *spacing)
        valid = np.isfinite(slope) & np.isfinite(aspect)
        if not np.any(valid):
            return json.dumps({"error": "No valid elevation data"})
        slope = slope[valid]
        aspect = aspect[valid]
        
        # Compute slope magnitude to identify flat pixels (slope < 5°)
        flat_mask = slope < 5.0
        flat_pct = float(flat_mask.sum()) / float(aspect.size) * 100
        
        directions = {
            "N": int(((aspect >= 337.5) | (aspect < 22.5)).sum()),
            "NE": int(((aspect >= 22.5) & (aspect < 67.5)).sum()),
            "E": int(((aspect >= 67.5) & (aspect < 112.5)).sum()),
            "SE": int(((aspect >= 112.5) & (aspect < 157.5)).sum()),
            "S": int(((aspect >= 157.5) & (aspect < 202.5)).sum()),
            "SW": int(((aspect >= 202.5) & (aspect < 247.5)).sum()),
            "W": int(((aspect >= 247.5) & (aspect < 292.5)).sum()),
            "NW": int(((aspect >= 292.5) & (aspect < 337.5)).sum())
        }
        
        total = sum(directions.values())
        distribution = {k: round(v / total * 100, 1) for k, v in directions.items()}
        dominant = max(directions, key=directions.get)
        
        # --------------------------------------------------------
        # Sun exposure rating for solar suitability
        # --------------------------------------------------------
        # Flat terrain (slope < 5°) is FAVORABLE for solar: panels
        # can be mounted at any tilt/azimuth, so aspect is irrelevant.
        # Only count sloped pixels when evaluating sun exposure.
        # 
        # Rating logic:
        #   - flat_pct >= 60%  → "good" (flat terrain dominates)
        #   - Otherwise, score sloped pixels by direction:
        #     S/SE/SW = favorable, E/W = neutral, N/NE/NW = unfavorable
        #     favorable > 50% of sloped → "good"
        #     favorable > 30% of sloped → "moderate"
        #     else → "limited"
        if flat_pct >= 60.0:
            sun_exposure = "good"
            sun_note = f"{flat_pct:.0f}% of terrain is flat — panels can face any direction (optimal for south-facing mounting)"
        else:
            # Only consider sloped pixels
            sloped_total = total - int(flat_mask.sum())  # approximate: flat_mask is per-pixel
            if sloped_total > 0:
                favorable = directions.get("S", 0) + directions.get("SE", 0) + directions.get("SW", 0)
                unfavorable = directions.get("N", 0) + directions.get("NE", 0) + directions.get("NW", 0)
                fav_ratio = favorable / total  # as fraction of all pixels
                unfav_ratio = unfavorable / total
                
                if fav_ratio > 0.50:
                    sun_exposure = "good"
                    sun_note = f"Majority of slopes face south/SE/SW — favorable for solar"
                elif fav_ratio > 0.30:
                    sun_exposure = "moderate"
                    sun_note = f"{fav_ratio*100:.0f}% south-facing slopes, {flat_pct:.0f}% flat terrain"
                elif unfav_ratio > 0.50:
                    sun_exposure = "limited"
                    sun_note = f"Majority of slopes face north — reduced solar exposure"
                else:
                    sun_exposure = "moderate"
                    sun_note = f"Mixed slope aspects ({flat_pct:.0f}% flat, {fav_ratio*100:.0f}% south-facing)"
            else:
                sun_exposure = "good"
                sun_note = "Terrain is effectively flat — optimal for solar"
        
        result = {
            "dominant_direction": dominant,
            "direction_distribution_percent": distribution,
            "flat_terrain_percent": round(flat_pct, 1),
            "sun_exposure": sun_exposure,
            "sun_exposure_note": sun_note,
            **_source_provenance(_DEM_SOURCE, items, bbox, window, int(aspect.size), spacing=spacing),
        }
        
        logger.info(f"[TOOL] Aspect: dominant {dominant}, flat {flat_pct:.0f}%, sun exposure {sun_exposure}")
        return json.dumps(result)
            
    except LookupError:
        return json.dumps({"error": "No DEM data available"})
    except Exception as e:
        logger.error(f"[TOOL] Aspect analysis failed: {e}")
        return json.dumps({"error": str(e)})


def find_flat_areas(latitude: float, longitude: float, radius_km: float = 5.0, max_slope_degrees: float = 5.0) -> str:
    """Find flat areas suitable for landing zones, construction, or camps. Returns 
    percentage of flat land and suitability assessment.
    Use when user asks about landing zones, flat ground, or buildable areas.
    
    :param latitude: Center latitude of the area to analyze
    :param longitude: Center longitude of the area to analyze
    :param radius_km: Radius in kilometers for analysis area (default 5.0)
    :param max_slope_degrees: Maximum slope in degrees to consider flat (default 5.0)
    :return: JSON string with flat area percentage and suitability
    """
    try:
        logger.info(f"[TOOL] find_flat_areas at ({latitude:.4f}, {longitude:.4f}), max_slope={max_slope_degrees} deg")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items, window, spacing, error = _dem_surface(bbox, latitude)
        if error:
            return json.dumps({"error": error})
        slope, _ = slope_aspect_degrees(window.data, *spacing)
        slope = slope[np.isfinite(slope)]
        if slope.size == 0:
            return json.dumps({"error": "No valid elevation data"})
        
        flat_mask = slope < max_slope_degrees
        flat_pct = float(np.sum(flat_mask) / flat_mask.size * 100)
        
        suitable = "excellent" if flat_pct > 50 else "good" if flat_pct > 20 else "limited" if flat_pct > 5 else "poor"
        
        result = {
            "flat_area_percent": round(flat_pct, 1),
            "slope_threshold_degrees": max_slope_degrees,
            "suitability_for_landing": suitable,
            "recommendation": f"{'Abundant' if flat_pct > 30 else 'Some' if flat_pct > 10 else 'Limited'} flat areas available within {radius_km}km radius",
            **_source_provenance(_DEM_SOURCE, items, bbox, window, int(slope.size), spacing=spacing),
        }
        
        logger.info(f"[TOOL] Flat areas: {flat_pct:.1f}% below {max_slope_degrees} deg")
        return json.dumps(result)
            
    except LookupError:
        return json.dumps({"error": "No DEM data available"})
    except Exception as e:
        logger.error(f"[TOOL] Flat area search failed: {e}")
        return json.dumps({"error": str(e)})


def analyze_flood_risk(latitude: float, longitude: float, radius_km: float = 5.0) -> str:
    """Analyze flood risk using JRC Global Surface Water historical data. Returns water 
    occurrence percentage (0-100%) indicating how often the area has been covered by water,
    flood risk level (LOW/MODERATE/HIGH), and permitting recommendation.
    
    :param latitude: Center latitude of the area to analyze
    :param longitude: Center longitude of the area to analyze
    :param radius_km: Radius in kilometers for analysis area (default 5.0)
    :return: JSON string with flood risk assessment and permitting status
    """
    try:
        logger.info(f"[TOOL] analyze_flood_risk at ({latitude:.4f}, {longitude:.4f})")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items = _search_items("jrc-gsw", bbox)
        
        if not items:
            return json.dumps({"error": "No JRC Global Surface Water data available", "flood_risk": "unknown"})
        
        items, window = _read_items_mosaic(items, "occurrence", bbox, categorical=True)
        occurrence = window.data
        valid_mask = np.isfinite(occurrence) & (occurrence <= 100)
        if not np.any(valid_mask):
            return json.dumps({"error": "No valid water occurrence data", "flood_risk": "unknown"})
        
        valid_data = occurrence[valid_mask]
        
        mean_occurrence = float(np.mean(valid_data))
        max_occurrence = float(np.max(valid_data))
        pct_ever_flooded = float(np.sum(valid_data > 0) / len(valid_data) * 100)
        pct_frequently_flooded = float(np.sum(valid_data > 25) / len(valid_data) * 100)
        
        if max_occurrence > 50 or pct_frequently_flooded > 10:
            risk_level = "HIGH"
            permitting_status = "NOT RECOMMENDED"
            risk_reason = "Significant historical flooding observed"
        elif max_occurrence > 10 or pct_ever_flooded > 20:
            risk_level = "MODERATE"
            permitting_status = "CONDITIONAL"
            risk_reason = "Some historical flooding, mitigation may be required"
        else:
            risk_level = "LOW"
            permitting_status = "SUITABLE"
            risk_reason = "Minimal historical flooding"
        
        result = {
            "mean_water_occurrence_percent": round(mean_occurrence, 1),
            "max_water_occurrence_percent": round(max_occurrence, 1),
            "area_ever_flooded_percent": round(pct_ever_flooded, 1),
            "area_frequently_flooded_percent": round(pct_frequently_flooded, 1),
            "flood_risk_level": risk_level,
            "permitting_status": permitting_status,
            "risk_reason": risk_reason,
            **_source_provenance(
                _jrc_source_label(items),
                items,
                bbox,
                window,
                int(valid_data.size),
                include_period=True,
            ),
        }
        
        logger.info(f"[TOOL] Flood risk: {risk_level} (max occurrence: {max_occurrence:.0f}%)")
        return json.dumps(result)
            
    except Exception as e:
        logger.error(f"[TOOL] Flood risk analysis failed: {e}")
        return json.dumps({"error": str(e), "flood_risk": "unknown"})


def analyze_water_proximity(latitude: float, longitude: float, radius_km: float = 5.0, required_setback_meters: float = 500.0) -> str:
    """Calculate distance to nearest water body for setback requirements. Returns 
    estimated minimum distance to water based on JRC Global Surface Water.
    Use for permitting to verify buffer zones (e.g., 500m from wetlands).
    
    :param latitude: Center latitude of site to analyze
    :param longitude: Center longitude of site to analyze
    :param radius_km: Search radius in kilometers (default 5.0)
    :param required_setback_meters: Required setback distance from water in meters (default 500.0)
    :return: JSON string with water proximity and setback compliance
    """
    try:
        from scipy import ndimage
        
        logger.info(f"[TOOL] analyze_water_proximity at ({latitude:.4f}, {longitude:.4f})")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items = _search_items("jrc-gsw", bbox)
        
        if not items:
            return json.dumps({"error": "No JRC Global Surface Water data available"})
        
        items, window = _read_items_mosaic(items, "occurrence", bbox, categorical=True)
        occurrence = window.data
        observed = np.isfinite(occurrence) & (occurrence <= 100)
        if not np.any(observed):
            return json.dumps({"error": "No valid water occurrence data"})
        water_mask = observed & (occurrence > 10)
        spacing = _cell_spacing(window, latitude)
        provenance = _source_provenance(
            _jrc_source_label(items),
            items,
            bbox,
            window,
            int(observed.sum()),
            spacing=spacing,
            include_period=True,
        )
        
        if not np.any(water_mask):
            return json.dumps({
                "water_detected": False,
                "nearest_water_meters": "None within search radius",
                "setback_requirement_meters": required_setback_meters,
                "setback_satisfied": True,
                "permitting_status": "SUITABLE",
                "recommendation": "No significant water bodies detected within analysis area",
                **provenance,
            })
        
        # Latitude-aware metric sampling: longitude cells narrow northward, so
        # a fixed 30 m cell overstated east-west distance by ~50% at 49 N.
        distance_meters = ndimage.distance_transform_edt(~water_mask, sampling=spacing)
        site_row, site_col = window.pixel_index(longitude, latitude)
        center_distance_meters = float(distance_meters[site_row, site_col])
        
        setback_satisfied = bool(center_distance_meters >= required_setback_meters)
        
        if setback_satisfied:
            status = "SUITABLE"
            recommendation = f"Site is {center_distance_meters:.0f}m from nearest water body, exceeds {required_setback_meters:.0f}m requirement"
        else:
            status = "NOT SUITABLE"
            recommendation = f"Site is only {center_distance_meters:.0f}m from water, does not meet {required_setback_meters:.0f}m setback requirement"
        
        water_percent = float(np.sum(water_mask) / np.sum(observed) * 100)
        
        result = {
            "water_detected": True,
            "nearest_water_meters": round(center_distance_meters, 0),
            "setback_requirement_meters": required_setback_meters,
            "setback_satisfied": setback_satisfied,
            "water_area_percent": round(water_percent, 1),
            "permitting_status": status,
            "recommendation": recommendation,
            **provenance,
        }
        
        logger.info(f"[TOOL] Water proximity: {center_distance_meters:.0f}m, setback {'OK' if setback_satisfied else 'FAILED'}")
        return json.dumps(result)
            
    except ImportError:
        return json.dumps({"error": "scipy not available for distance calculation"})
    except Exception as e:
        logger.error(f"[TOOL] Water proximity analysis failed: {e}")
        return json.dumps({"error": str(e)})


def analyze_environmental_sensitivity(latitude: float, longitude: float, radius_km: float = 5.0) -> str:
    """Identify environmentally sensitive areas using ESA WorldCover land classification. 
    Detects wetlands, forests, mangroves, and other protected land types.
    Use for environmental permitting to check for protected habitats.
    
    :param latitude: Center latitude of the area to analyze
    :param longitude: Center longitude of the area to analyze
    :param radius_km: Radius in kilometers for analysis area (default 5.0)
    :return: JSON string with land cover breakdown and environmental sensitivity
    """
    try:
        logger.info(f"[TOOL] analyze_environmental_sensitivity at ({latitude:.4f}, {longitude:.4f})")
        
        bbox = _calculate_bbox(latitude, longitude, radius_km)
        items = _search_items("esa-worldcover", bbox)
        
        if not items:
            return json.dumps({"error": "No ESA WorldCover data available"})
        
        items, window = _read_items_mosaic(items, "map", bbox, categorical=True)
        landcover = window.data
        classified = np.isfinite(landcover)
        total_pixels = int(classified.sum())
        if total_pixels == 0:
            return json.dumps({"error": "No valid land cover data"})
        
        # ESA WorldCover v200 legend. Snow/ice and moss/lichen dominate much of
        # northern Canada, so omitting them misstates the dominant class.
        class_counts = {
            "tree_cover": float(np.sum(landcover == 10) / total_pixels * 100),
            "shrubland": float(np.sum(landcover == 20) / total_pixels * 100),
            "grassland": float(np.sum(landcover == 30) / total_pixels * 100),
            "cropland": float(np.sum(landcover == 40) / total_pixels * 100),
            "built_up": float(np.sum(landcover == 50) / total_pixels * 100),
            "bare_sparse": float(np.sum(landcover == 60) / total_pixels * 100),
            "snow_and_ice": float(np.sum(landcover == 70) / total_pixels * 100),
            "permanent_water": float(np.sum(landcover == 80) / total_pixels * 100),
            "herbaceous_wetland": float(np.sum(landcover == 90) / total_pixels * 100),
            "mangroves": float(np.sum(landcover == 95) / total_pixels * 100),
            "moss_and_lichen": float(np.sum(landcover == 100) / total_pixels * 100),
        }
        
        sensitive_classes = ["tree_cover", "herbaceous_wetland", "mangroves", "permanent_water"]
        sensitive_percent = sum(class_counts[c] for c in sensitive_classes)
        
        constraints = []
        if class_counts["herbaceous_wetland"] > 5:
            constraints.append(f"Wetlands ({class_counts['herbaceous_wetland']:.1f}%) - may require wetland mitigation")
        if class_counts["mangroves"] > 1:
            constraints.append(f"Mangroves ({class_counts['mangroves']:.1f}%) - protected habitat, development restricted")
        if class_counts["tree_cover"] > 30:
            constraints.append(f"Forest ({class_counts['tree_cover']:.1f}%) - may require deforestation permit")
        if class_counts["permanent_water"] > 10:
            constraints.append(f"Water bodies ({class_counts['permanent_water']:.1f}%) - setback requirements apply")
        
        if sensitive_percent > 40:
            sensitivity_level = "HIGH"
            permitting_status = "NOT RECOMMENDED"
        elif sensitive_percent > 15:
            sensitivity_level = "MODERATE"
            permitting_status = "CONDITIONAL"
        else:
            sensitivity_level = "LOW"
            permitting_status = "SUITABLE"
        
        dominant = max(class_counts, key=class_counts.get)
        period = _temporal_coverage(items)
        source_label = (
            f"ESA WorldCover {period[:4]} (10m resolution)"
            if period
            else "ESA WorldCover (10m resolution)"
        )
        
        result = {
            "land_cover_breakdown_percent": {k: round(v, 1) for k, v in class_counts.items() if v > 0.5},
            "dominant_land_cover": dominant.replace("_", " ").title(),
            "sensitive_area_percent": round(sensitive_percent, 1),
            "environmental_sensitivity": sensitivity_level,
            "permitting_status": permitting_status,
            "environmental_constraints": constraints if constraints else ["No major environmental constraints identified"],
            **_source_provenance(
                source_label,
                items,
                bbox,
                window,
                total_pixels,
                include_period=True,
            ),
        }
        
        logger.info(f"[TOOL] Environmental sensitivity: {sensitivity_level} ({sensitive_percent:.0f}% sensitive)")
        return json.dumps(result)
            
    except Exception as e:
        logger.error(f"[TOOL] Environmental sensitivity analysis failed: {e}")
        return json.dumps({"error": str(e)})


def create_terrain_functions() -> Set[Callable]:
    """Create the set of terrain analysis functions for FunctionTool.
    
    Returns a Set[Callable] that can be passed to FunctionTool().
    Each function uses docstring-based parameter descriptions.
    """
    return {
        get_elevation_analysis,
        get_slope_analysis,
        get_aspect_analysis,
        find_flat_areas,
        analyze_flood_risk,
        analyze_water_proximity,
        analyze_environmental_sensitivity,
    }
