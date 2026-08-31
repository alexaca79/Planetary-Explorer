"""Generate synthetic Canadian 2026 fallback data for local agent demos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
LAKEHOUSE_DIR = ROOT / "data" / "lakehouse_seed"
RESILIENCE_DIR = (
    ROOT
    / "planetary-explorer"
    / "container-app"
    / "agents"
    / "resilience"
    / "seed_data"
)
RETRIEVAL_DATE = "2026-08-26T00:00:00+00:00"
DEMO_SOURCE = "Planetary-Explorer-Canadian-Demo-2026"
DEMO_URL = "https://github.com/microsoft/Planetary-Explorer"


def _source_fields() -> dict[str, str]:
    return {
        "source_dataset": DEMO_SOURCE,
        "source_url": DEMO_URL,
        "source_authority": "synthetic_demo",
        "retrieval_date": RETRIEVAL_DATE,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_lakehouse_tables() -> None:
    source = _source_fields()
    tables: dict[str, tuple[list[str], list[dict[str, Any]]]] = {
        "candidate_sites": (
            [
                "site_id", "name", "state", "county", "parcel_acres",
                "current_land_use", "screening_status", "latitude", "longitude",
                "zoning", "owner_type", "source_dataset", "source_url",
                "source_authority", "retrieval_date",
            ],
            [
                {"site_id": "ca-ab-cgy-01", "name": "Calgary North Candidate", "state": "AB", "county": "ROCKY VIEW", "parcel_acres": 185.0, "current_land_use": "INDUSTRIAL", "screening_status": "demo_candidate", "latitude": 51.180, "longitude": -114.050, "zoning": "industrial", "owner_type": "private", **source},
                {"site_id": "ca-ab-edm-01", "name": "Edmonton East Candidate", "state": "AB", "county": "STRATHCONA", "parcel_acres": 220.0, "current_land_use": "BROWNFIELD", "screening_status": "demo_candidate", "latitude": 53.530, "longitude": -113.300, "zoning": "industrial", "owner_type": "private", **source},
                {"site_id": "ca-qc-mtl-01", "name": "Montreal East Candidate", "state": "QC", "county": "MONTREAL", "parcel_acres": 140.0, "current_land_use": "INDUSTRIAL", "screening_status": "demo_candidate", "latitude": 45.590, "longitude": -73.500, "zoning": "industrial", "owner_type": "public_private", **source},
                {"site_id": "ca-on-tor-01", "name": "Toronto West Candidate", "state": "ON", "county": "PEEL", "parcel_acres": 125.0, "current_land_use": "INDUSTRIAL", "screening_status": "demo_candidate", "latitude": 43.650, "longitude": -79.700, "zoning": "employment", "owner_type": "private", **source},
                {"site_id": "ca-bc-van-01", "name": "Vancouver Inland Candidate", "state": "BC", "county": "FRASER VALLEY", "parcel_acres": 95.0, "current_land_use": "INDUSTRIAL", "screening_status": "demo_candidate", "latitude": 49.100, "longitude": -122.300, "zoning": "industrial", "owner_type": "private", **source},
                {"site_id": "ca-ns-hal-01", "name": "Halifax Logistics Candidate", "state": "NS", "county": "HALIFAX", "parcel_acres": 110.0, "current_land_use": "PORT_INDUSTRIAL", "screening_status": "demo_candidate", "latitude": 44.720, "longitude": -63.650, "zoning": "industrial", "owner_type": "public_private", **source},
            ],
        ),
        "power_infrastructure": (
            [
                "asset_id", "type", "name", "state", "county", "voltage_kv",
                "capacity_mw", "status", "latitude", "longitude", "owner_utility",
                "source_dataset", "source_url", "source_authority", "retrieval_date",
            ],
            [
                {"asset_id": "ca-grid-ab-01", "type": "substation", "name": "Calgary North 240 kV Demo", "state": "AB", "county": "ROCKY VIEW", "voltage_kv": 240.0, "capacity_mw": 420.0, "status": "in_service", "latitude": 51.170, "longitude": -114.020, "owner_utility": "Synthetic Alberta Utility", **source},
                {"asset_id": "ca-grid-ab-02", "type": "substation", "name": "Edmonton East 240 kV Demo", "state": "AB", "county": "STRATHCONA", "voltage_kv": 240.0, "capacity_mw": 360.0, "status": "in_service", "latitude": 53.540, "longitude": -113.260, "owner_utility": "Synthetic Alberta Utility", **source},
                {"asset_id": "ca-grid-qc-01", "type": "substation", "name": "Montreal East 315 kV Demo", "state": "QC", "county": "MONTREAL", "voltage_kv": 315.0, "capacity_mw": 520.0, "status": "in_service", "latitude": 45.600, "longitude": -73.470, "owner_utility": "Synthetic Quebec Utility", **source},
                {"asset_id": "ca-grid-on-01", "type": "substation", "name": "Peel 230 kV Demo", "state": "ON", "county": "PEEL", "voltage_kv": 230.0, "capacity_mw": 410.0, "status": "in_service", "latitude": 43.670, "longitude": -79.680, "owner_utility": "Synthetic Ontario Utility", **source},
                {"asset_id": "ca-grid-bc-01", "type": "substation", "name": "Fraser Valley 230 kV Demo", "state": "BC", "county": "FRASER VALLEY", "voltage_kv": 230.0, "capacity_mw": 280.0, "status": "in_service", "latitude": 49.120, "longitude": -122.270, "owner_utility": "Synthetic British Columbia Utility", **source},
                {"asset_id": "ca-grid-ns-01", "type": "substation", "name": "Halifax 138 kV Demo", "state": "NS", "county": "HALIFAX", "voltage_kv": 138.0, "capacity_mw": 180.0, "status": "in_service", "latitude": 44.700, "longitude": -63.620, "owner_utility": "Synthetic Nova Scotia Utility", **source},
            ],
        ),
        "water_assets": (
            [
                "asset_id", "name", "type", "state", "latitude", "longitude",
                "huc_code", "permitted_withdrawal_mgd", "available_capacity_mgd",
                "source_dataset", "source_url", "source_authority", "retrieval_date",
            ],
            [
                {"asset_id": "ca-water-ab-01", "name": "Bow River Demo Intake", "type": "river", "state": "AB", "latitude": 51.100, "longitude": -114.120, "huc_code": None, "permitted_withdrawal_mgd": 18.0, "available_capacity_mgd": 7.5, **source},
                {"asset_id": "ca-water-ab-02", "name": "North Saskatchewan Demo Intake", "type": "river", "state": "AB", "latitude": 53.530, "longitude": -113.430, "huc_code": None, "permitted_withdrawal_mgd": 22.0, "available_capacity_mgd": 9.0, **source},
                {"asset_id": "ca-water-qc-01", "name": "St. Lawrence Demo Intake", "type": "river", "state": "QC", "latitude": 45.550, "longitude": -73.510, "huc_code": None, "permitted_withdrawal_mgd": 30.0, "available_capacity_mgd": 12.0, **source},
                {"asset_id": "ca-water-on-01", "name": "Lake Ontario Demo Intake", "type": "lake", "state": "ON", "latitude": 43.620, "longitude": -79.500, "huc_code": None, "permitted_withdrawal_mgd": 28.0, "available_capacity_mgd": 10.0, **source},
                {"asset_id": "ca-water-bc-01", "name": "Fraser River Demo Intake", "type": "river", "state": "BC", "latitude": 49.080, "longitude": -122.310, "huc_code": None, "permitted_withdrawal_mgd": 14.0, "available_capacity_mgd": 5.0, **source},
                {"asset_id": "ca-water-ns-01", "name": "Halifax Regional Demo Supply", "type": "reservoir", "state": "NS", "latitude": 44.750, "longitude": -63.660, "huc_code": None, "permitted_withdrawal_mgd": 9.0, "available_capacity_mgd": 3.0, **source},
            ],
        ),
        "existing_data_centers": (
            [
                "facility_id", "operator", "mw_capacity", "mw_available",
                "ppa_clean_energy_pct", "latency_metro_ms", "year_online", "latitude",
                "longitude", "address", "source_dataset", "source_url",
                "source_authority", "retrieval_date",
            ],
            [
                {"facility_id": "ca-dc-cgy-01", "operator": "Calgary Demo Compute", "mw_capacity": 42.0, "mw_available": 8.0, "ppa_clean_energy_pct": 65.0, "latency_metro_ms": 4.0, "year_online": 2022, "latitude": 51.080, "longitude": -114.020, "address": "Synthetic Calgary location", **source},
                {"facility_id": "ca-dc-edm-01", "operator": "Edmonton Demo Compute", "mw_capacity": 30.0, "mw_available": 6.0, "ppa_clean_energy_pct": 70.0, "latency_metro_ms": 5.0, "year_online": 2023, "latitude": 53.560, "longitude": -113.420, "address": "Synthetic Edmonton location", **source},
                {"facility_id": "ca-dc-mtl-01", "operator": "Montreal Demo Compute", "mw_capacity": 55.0, "mw_available": 10.0, "ppa_clean_energy_pct": 95.0, "latency_metro_ms": 3.0, "year_online": 2021, "latitude": 45.540, "longitude": -73.550, "address": "Synthetic Montreal location", **source},
                {"facility_id": "ca-dc-tor-01", "operator": "Toronto Demo Compute", "mw_capacity": 60.0, "mw_available": 7.0, "ppa_clean_energy_pct": 55.0, "latency_metro_ms": 2.0, "year_online": 2020, "latitude": 43.680, "longitude": -79.620, "address": "Synthetic Toronto location", **source},
                {"facility_id": "ca-dc-van-01", "operator": "Vancouver Demo Compute", "mw_capacity": 38.0, "mw_available": 4.0, "ppa_clean_energy_pct": 90.0, "latency_metro_ms": 3.0, "year_online": 2024, "latitude": 49.160, "longitude": -122.920, "address": "Synthetic Vancouver location", **source},
            ],
        ),
        "site_scores_derived": (
            [
                "site_id", "water_score", "hazard_score", "grid_score",
                "latency_score", "overall_score", "confidence", "pareto_rank",
                "last_scored_at", "explanation_blob", "evidence_doc_ids",
            ],
            [],
        ),
    }

    manifest: dict[str, Any] = {
        "scope": "Synthetic Canadian demonstration data for 2026",
        "authoritative": False,
        "generated_at": RETRIEVAL_DATE,
        "tables": {},
    }
    for name, (columns, rows) in tables.items():
        frame = pd.DataFrame(rows, columns=columns)
        path = LAKEHOUSE_DIR / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        manifest["tables"][name] = {
            "rows": len(frame),
            "columns": columns,
            "path": path.relative_to(ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
        }
    _write_json(LAKEHOUSE_DIR / "manifest.json", manifest)


def _write_resilience_data() -> None:
    facilities = [
        {"facility_id": "bc-dc-vancouver-01", "name": "Vancouver Distribution Centre", "type": "distribution", "lat": 49.2057, "lng": -123.1127, "region": "BC", "city": "Vancouver", "criticality": 0.90, "heat_threshold_f": 88.0, "headcount": 310, "notes": "Synthetic 2026 demo facility; port and Fraser River disruption exposure."},
        {"facility_id": "bc-log-prince-george-01", "name": "Prince George Logistics Hub", "type": "logistics", "lat": 53.9171, "lng": -122.7497, "region": "BC", "city": "Prince George", "criticality": 0.66, "heat_threshold_f": 91.0, "headcount": 140, "notes": "Synthetic 2026 demo facility; wildfire and highway corridor exposure."},
        {"facility_id": "ab-dc-calgary-01", "name": "Calgary Data Centre", "type": "data_center", "lat": 51.0447, "lng": -114.0719, "region": "AB", "city": "Calgary", "criticality": 0.94, "heat_threshold_f": 91.0, "cooling_water_m3_per_day": 7200, "headcount": 210, "notes": "Synthetic 2026 demo facility; cooling and grid continuity are critical."},
        {"facility_id": "ab-asm-edmonton-01", "name": "Edmonton Systems Assembly", "type": "assembly", "lat": 53.5461, "lng": -113.4938, "region": "AB", "city": "Edmonton", "criticality": 0.78, "heat_threshold_f": 90.0, "headcount": 860, "notes": "Synthetic 2026 demo facility; receives components from Ontario and Quebec."},
        {"facility_id": "sk-sub-saskatoon-01", "name": "Saskatoon Sub-Assembly", "type": "sub_assembly", "lat": 52.1579, "lng": -106.6702, "region": "SK", "city": "Saskatoon", "criticality": 0.61, "heat_threshold_f": 94.0, "headcount": 430, "notes": "Synthetic 2026 demo facility; Prairie heat, smoke, and rail exposure."},
        {"facility_id": "mb-dc-winnipeg-01", "name": "Winnipeg Distribution Hub", "type": "distribution", "lat": 49.8954, "lng": -97.1385, "region": "MB", "city": "Winnipeg", "criticality": 0.72, "heat_threshold_f": 93.0, "headcount": 260, "notes": "Synthetic 2026 demo facility; central transshipment and flood exposure."},
        {"facility_id": "on-fab-toronto-01", "name": "Toronto Advanced Manufacturing", "type": "fab", "lat": 43.6532, "lng": -79.3832, "region": "ON", "city": "Toronto", "criticality": 0.96, "heat_threshold_f": 92.0, "cooling_water_m3_per_day": 10500, "headcount": 1900, "notes": "Synthetic 2026 demo facility; Great Lakes supply dependency."},
        {"facility_id": "on-rd-ottawa-01", "name": "Ottawa Research Campus", "type": "rd", "lat": 45.4215, "lng": -75.6972, "region": "ON", "city": "Ottawa", "criticality": 0.52, "heat_threshold_f": 91.0, "headcount": 520, "notes": "Synthetic 2026 demo facility; research and process design centre."},
        {"facility_id": "qc-pkg-montreal-01", "name": "Montreal Packaging Plant", "type": "packaging", "lat": 45.5019, "lng": -73.5674, "region": "QC", "city": "Montreal", "criticality": 0.74, "heat_threshold_f": 91.0, "headcount": 690, "notes": "Synthetic 2026 demo facility; national packaging and distribution."},
        {"facility_id": "ns-port-halifax-01", "name": "Halifax Port Distribution", "type": "distribution", "lat": 44.6488, "lng": -63.5752, "region": "NS", "city": "Halifax", "criticality": 0.81, "heat_threshold_f": 86.0, "headcount": 240, "notes": "Synthetic 2026 demo facility; Atlantic port and coastal storm exposure."},
    ]
    edges = [
        {"src_facility_id": "on-rd-ottawa-01", "dst_facility_id": "on-fab-toronto-01", "kind": "process_designs", "lead_time_days": 0, "weekly_volume": 1.0},
        {"src_facility_id": "on-fab-toronto-01", "dst_facility_id": "ab-asm-edmonton-01", "kind": "components", "lead_time_days": 3, "weekly_volume": 1.0},
        {"src_facility_id": "sk-sub-saskatoon-01", "dst_facility_id": "ab-asm-edmonton-01", "kind": "sub_assemblies", "lead_time_days": 1, "weekly_volume": 0.8},
        {"src_facility_id": "ab-asm-edmonton-01", "dst_facility_id": "qc-pkg-montreal-01", "kind": "assembled_units", "lead_time_days": 4, "weekly_volume": 0.9},
        {"src_facility_id": "qc-pkg-montreal-01", "dst_facility_id": "bc-dc-vancouver-01", "kind": "finished_goods", "lead_time_days": 5, "weekly_volume": 0.6},
        {"src_facility_id": "qc-pkg-montreal-01", "dst_facility_id": "mb-dc-winnipeg-01", "kind": "finished_goods", "lead_time_days": 3, "weekly_volume": 0.8},
        {"src_facility_id": "qc-pkg-montreal-01", "dst_facility_id": "ns-port-halifax-01", "kind": "finished_goods", "lead_time_days": 2, "weekly_volume": 0.5},
        {"src_facility_id": "mb-dc-winnipeg-01", "dst_facility_id": "bc-dc-vancouver-01", "kind": "transshipment", "lead_time_days": 3, "weekly_volume": 0.4},
        {"src_facility_id": "bc-dc-vancouver-01", "dst_facility_id": "bc-log-prince-george-01", "kind": "regional_freight", "lead_time_days": 1, "weekly_volume": 0.5},
        {"src_facility_id": "ns-port-halifax-01", "dst_facility_id": "qc-pkg-montreal-01", "kind": "imported_components", "lead_time_days": 2, "weekly_volume": 0.6},
    ]
    playbooks = [
        {"playbook_id": "heat-alberta-2026", "title": "Alberta Heat Continuity Playbook", "hazards": ["heat"], "region": "AB", "facility_hint": ["ab-dc-calgary-01", "ab-asm-edmonton-01"], "owner": "Canadian Operations Resilience Team", "last_reviewed": "2026-06", "trigger": "Three-day maximum temperature forecast above the local facility threshold or an Alberta grid alert.", "tier1_actions": ["Pre-cool critical rooms overnight.", "Verify backup power and cooling-water reserves.", "Move outdoor work to morning shifts."], "tier2_actions": ["Reduce non-critical compute load.", "Move assembly volume to Ontario where capacity permits."], "stand_down": "Temperatures remain below the site threshold for 48 hours and grid alerts clear.", "summary": "Synthetic 2026 demo playbook for heat and cooling continuity at Alberta facilities."},
        {"playbook_id": "wildfire-british-columbia-2026", "title": "British Columbia Wildfire and Smoke Response", "hazards": ["wildfire"], "region": "BC", "facility_hint": ["bc-dc-vancouver-01", "bc-log-prince-george-01"], "owner": "Western Canada Operations", "last_reviewed": "2026-07", "trigger": "Air quality health index reaches high risk or an active fire threatens a primary corridor.", "tier1_actions": ["Issue respiratory protection for outdoor staff.", "Use maximum building filtration.", "Pre-position freight on alternate routes."], "tier2_actions": ["Suspend exposed yard operations.", "Shift Vancouver-bound inventory through Winnipeg."], "stand_down": "Air quality returns to low risk and primary corridors reopen.", "summary": "Synthetic 2026 demo playbook for wildfire, smoke, and corridor disruption in British Columbia."},
        {"playbook_id": "prairie-flood-2026", "title": "Prairie Flood and Rail Continuity", "hazards": ["flood"], "region": "MB", "facility_hint": ["mb-dc-winnipeg-01", "sk-sub-saskatoon-01"], "owner": "Prairie Logistics", "last_reviewed": "2026-04", "trigger": "A flood warning affects the Red River corridor or a primary rail line is forecast to close.", "tier1_actions": ["Raise critical inventory above ground level.", "Reserve alternate trucking capacity.", "Advance east-west shipments."], "tier2_actions": ["Divert freight through Calgary.", "Activate temporary storage outside the floodplain."], "stand_down": "Flood warnings clear and road and rail service return to normal.", "summary": "Synthetic 2026 demo playbook for Manitoba flood and national transshipment continuity."},
        {"playbook_id": "vancouver-distribution-2026", "title": "Vancouver Distribution Centre Continuity", "hazards": ["heat", "wildfire", "flood"], "region": "BC", "facility_hint": ["bc-dc-vancouver-01", "bc-log-prince-george-01", "mb-dc-winnipeg-01"], "owner": "Pacific Distribution", "last_reviewed": "2026-08", "trigger": "Vancouver Distribution Centre is offline for 24 hours or port, rail, or flood disruption blocks inbound freight.", "tier1_actions": ["Route national inventory through Winnipeg.", "Use Prince George for northern deliveries.", "Notify customers of revised lead times."], "tier2_actions": ["Activate third-party storage in Calgary.", "Prioritize critical shipments for air freight."], "stand_down": "Vancouver throughput reaches 90 percent and the inbound queue falls below one day.", "summary": "Synthetic 2026 demo playbook for a 48-hour Vancouver distribution outage."},
        {"playbook_id": "atlantic-port-2026", "title": "Atlantic Port and Coastal Storm Continuity", "hazards": ["flood", "hurricane"], "region": "NS", "facility_hint": ["ns-port-halifax-01", "qc-pkg-montreal-01"], "owner": "Atlantic Canada Distribution", "last_reviewed": "2026-06", "trigger": "A coastal storm warning closes Halifax terminals or threatens power and road access.", "tier1_actions": ["Move inbound components to secure storage.", "Redirect urgent freight through Montreal.", "Verify generator fuel and communications."], "tier2_actions": ["Activate alternate Atlantic carrier capacity.", "Defer non-critical outbound shipments."], "stand_down": "Port operations and utility service are stable for 24 hours.", "summary": "Synthetic 2026 demo playbook for Halifax coastal storm and port disruption."},
    ]
    _write_json(RESILIENCE_DIR / "facilities.json", facilities)
    _write_json(RESILIENCE_DIR / "supply_edges.json", edges)
    _write_json(RESILIENCE_DIR / "bcp_playbooks.json", playbooks)


def main() -> int:
    """Generate all Canadian demo data files."""
    LAKEHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    RESILIENCE_DIR.mkdir(parents=True, exist_ok=True)
    _write_lakehouse_tables()
    _write_resilience_data()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())