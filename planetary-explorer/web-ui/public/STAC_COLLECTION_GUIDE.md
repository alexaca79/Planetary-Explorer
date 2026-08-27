---
title: STAC Collection Availability Guide
description: Query Microsoft Planetary Computer collections with Canadian examples from 2026.
---

**Microsoft Planetary Computer | Planetary Explorer**

This guide helps you craft queries that return results for all 21 available satellite and geospatial collections.

---

## ⭐ Featured Collections

The following collections are production-ready, high-priority datasets optimized for reliable querying and visualization in Planetary Explorer.

### 🌍 Harmonized Landsat and Sentinel-2 (HLS) v2.0

**Collections:** `hls2-l30` (Landsat) and `hls2-s30` (Sentinel-2)

Harmonized Landsat Sentinel-2 (HLS) Version 2.0 provides consistent surface reflectance (SR) and top of atmosphere (TOA) brightness data from the Operational Land Imager (OLI) aboard the joint NASA/USGS Landsat 8 and Landsat 9 satellites and the Multi-Spectral Instrument (MSI) aboard the ESA (European Space Agency) Sentinel-2A, Sentinel-2B, and Sentinel-2C satellites.

**Specifications:**
- **Resolution:** 30m (harmonized from both sensors)
- **Temporal Coverage:** 2020-01-01 to Present
- **Revisit Time:** ~2-3 days (combined constellation)
- **Spectral Bands:** 11 harmonized bands (B02-B12)
- **Processing Level:** Surface reflectance (atmospherically corrected)

**How to Query:**
```
✅ "Show HLS Landsat imagery over British Columbia forests from 2026-05-01 to 2026-08-26"
✅ "Find HLS Sentinel-2 data for Saskatchewan agriculture from 2026-04-01 to 2026-08-26 with low cloud cover"
✅ "Display HLS imagery over the Mackenzie River from 2026-05-01 to 2026-06-30"
```

**Best Practices:**
- Use "recent" or "latest" for current data (last 30 days)
- Mention "low cloud cover" for optical imagery
- Ideal for vegetation monitoring and land cover change detection
- Seamlessly combines Landsat and Sentinel-2 for consistent time-series

**Tags:** `Sentinel` `Landsat` `HLS` `Satellite` `Global` `Imagery`

---

### 🛰️ Landsat Collection 2

**Collections:** `landsat-c2-l2` (Surface Reflectance), `landsat-c2-l1` (Historical MSS)

The Landsat program provides a comprehensive, continuous archive of multispectral imagery of the Earth's surface from 1972 to present. The longest-running Earth observation program.

**Specifications:**
- **Resolution:** 30m (OLI/TIRS), 79m (MSS historical)
- **Temporal Coverage:** 
  - L2 (Surface Reflectance): 1982-08-22 to Present
  - L1 (MSS Historical): 1972-07-25 to 2013-01-07
- **Platform:** Landsat 4-9 (L2), Landsat 1-5 MSS (L1)
- **Spectral Bands:** 11 bands (L8/L9), 4 bands (MSS)

**How to Query:**
```
✅ "Show Landsat imagery over Halifax from 2026-01-01 to 2026-08-26"
✅ "Find Landsat images of Toronto urban development from 2026-01-01 to 2026-08-26"
✅ "Display Landsat data for British Columbia forest monitoring from 2026-05-01 to 2026-08-26"
✅ "Show Landsat imagery of Hudson Bay from 2026-06-01 to 2026-08-26"
```

**Best Practices:**
- Use "recent" or "latest" for L2 surface reflectance
- Specify "historical" or "1970s-1990s" for L1 MSS data
- 16-day revisit time per satellite
- Ideal for long-term change detection (50+ year archive)

**Tags:** `Landsat` `USGS` `NASA` `Satellite` `Global` `Imagery`

---

### 🌡️ MODIS Version 6.1 Products

**Collections:** 14 MODIS products including vegetation, temperature, fire, and snow

The MODIS instrument operates on both the Terra and Aqua spacecraft, covering the entire surface of the Earth within one or two days. The derived data products describe atmosphere, cryosphere, land, and ocean features utilized in studies across various disciplines.

**Specifications:**
- **Resolution:** 250m, 500m, and 1km (varies by product)
- **Temporal Coverage:** 2000-02-16 to Present
- **Platform:** Terra + Aqua combined
- **Revisit Time:** Daily to 8-day composites

**Featured Products:**
- **MODIS-43A4-061** (NBAR): BRDF-corrected reflectance (500m)
- **MODIS-09A1/09Q1-061**: Surface reflectance (500m/250m)
- **MODIS-13A1/13Q1-061**: Vegetation indices - NDVI/EVI (500m/250m)
- **MODIS-11A1-061**: Land surface temperature (1km)
- **MODIS-14A1/14A2-061**: Thermal anomalies/fire detection (1km)
- **MODIS-15A2H-061**: Leaf area index (500m)
- **MODIS-17A2H/17A3HGF-061**: Gross/Net primary production (500m)
- **MODIS-10A1-061**: Snow cover daily (500m)

**How to Query:**
```
✅ "Show MODIS vegetation indices over Saskatchewan from 2026-04-01 to 2026-08-26"
✅ "Find MODIS fire data across Alberta from 2026-05-01 to 2026-08-26"
✅ "Display MODIS land surface temperature over Toronto from 2026-05-01 to 2026-08-26"
✅ "Show MODIS snow cover over Quebec from 2026-02-01 to 2026-02-28"
```

**Best Practices:**
- ⚠️ **CRITICAL:** Use an explicit supported range, such as `2026-01-01/2026-08-26`
- **Do NOT use current dates** - MODIS has 3-6 month processing lag
- Ideal for global monitoring at moderate resolution
- Use for vegetation health, fire detection, thermal analysis, snow monitoring

**Tags:** `MODIS` `NASA` `USGS` `Satellite` `Global` `Imagery`

---

### 📡 Sentinel-1 Synthetic Aperture Radar (SAR)

**Collections:** `sentinel-1-rtc` (Radiometrically Terrain Corrected), `sentinel-1-grd` (Ground Range Detected)

Sentinel-1 comprises a constellation of two polar-orbiting satellites, operating day and night performing C-band synthetic aperture radar imaging. Weather-independent, cloud-penetrating radar.

**Specifications:**
- **Resolution:** 10m pixel spacing (~20m ground resolution)
- **Temporal Coverage:** 2014-10-10 to Present
- **Platform:** Sentinel-1A, Sentinel-1B, Sentinel-1C
- **Polarizations:** VV, VH, HH, HV
- **Revisit Time:** 6-12 days

**How to Query:**
```
✅ "Show Sentinel-1 RTC over the Red River, Manitoba from 2026-03-01 to 2026-05-31"
✅ "Find Sentinel-1 SAR data for ship detection near Vancouver from 2026-01-01 to 2026-08-26"
✅ "Display Sentinel-1 RTC over Halifax from 2026-01-01 to 2026-08-26 for coastal-storm monitoring"
```

**Best Practices:**
- **Weather-independent** - works through clouds and at night
- Use "recent" or "latest" for current monitoring
- RTC recommended for terrain analysis (includes terrain correction)
- GRD for general SAR applications
- Ideal for flood mapping, ship detection, change detection

**Tags:** `ESA` `Copernicus` `Sentinel` `C-Band` `SAR`

---

### 🌍 Sentinel-2 Level-2A

**Collection:** `sentinel-2-l2a`

The Sentinel-2 program provides global imagery in thirteen spectral bands at 10m-60m resolution and a revisit time of approximately five days. This dataset contains the global Sentinel-2 archive, from 2015 to the present, processed to L2A (bottom-of-atmosphere surface reflectance).

**Specifications:**
- **Resolution:** 10m (RGB+NIR), 20m (red edge+SWIR), 60m (coastal/water vapor)
- **Temporal Coverage:** 2015-06-27 to Present
- **Platform:** Sentinel-2A, Sentinel-2B
- **Spectral Bands:** 13 bands including red edge bands
- **Revisit Time:** ~5 days (with both satellites)

**How to Query:**
```
✅ "Show Sentinel-2 imagery over Toronto from 2026-06-01 to 2026-08-26 with low cloud cover"
✅ "Find Sentinel-2 images along the Mackenzie River from 2026-05-01 to 2026-06-30"
✅ "Display Sentinel-2 data for Halifax coastal monitoring from 2026-06-01 to 2026-08-26"
```

**Best Practices:**
- Mention "recent" or "latest" for current data (last 30 days)
- Always include "low cloud cover" or "clear sky" for best results
- Superior to Landsat for: higher resolution (10m vs 30m), red edge bands, faster revisit
- Ideal for vegetation analysis, land cover mapping, precision agriculture

**Tags:** `Sentinel` `Copernicus` `ESA` `Satellite` `Global` `Imagery` `Reflectance`

---

## 📅 Understanding Data Availability

Different satellite collections have different update schedules and data availability patterns. Use this guide to ensure your queries match the right time ranges for each collection type.

---

## 🎯 Quick Reference Table

| Collection | Resolution | Date Range to Use | Why |
|-----------|-----------|-------------------|-----|
| **NAIP** | 0.6m | No date needed | Updates every 2-3 years, use latest available |
| **Sentinel-2 L2A** | 10m | Last 30 days | Near real-time, updated continuously |
| **Landsat C2 L2** | 30m | Last 90 days | Near real-time, updated continuously |
| **HLS L30** | 30m | Last 30 days | Harmonized Landsat, recent data |
| **HLS S30** | 30m | Last 30 days | Harmonized Sentinel-2, recent data |
| **Copernicus DEM 30m** | 30m | No date needed | Static elevation dataset (2021) |
| **Copernicus DEM 90m** | 90m | No date needed | Static elevation dataset (2021) |
| **NASADEM** | 30m | No date needed | Static elevation dataset (2000) |
| **Sentinel-1 RTC** | 10-20m | Last 90 days | Radar data, updated continuously |
| **Sentinel-1 GRD** | 10-20m | Last 30 days | Radar data, updated continuously |
| **MODIS 09A1** (500m) | 500m | 2026-01-01 to 2026-08-26 | Verify collection availability |
| **MODIS 09Q1** (250m) | 250m | 2026-01-01 to 2026-08-26 | Verify collection availability |
| **MODIS 13A1** (NDVI 500m) | 500m | 2026-04-01 to 2026-08-26 | Growing-season example |
| **MODIS 13Q1** (NDVI 250m) | 250m | 2026-04-01 to 2026-08-26 | Growing-season example |
| **MODIS 15A2H** (LAI) | 500m | 2026-04-01 to 2026-08-26 | Growing-season example |
| **MODIS 17A2H** (GPP) | 500m | 2026-05-01 to 2026-08-26 | Productivity example |
| **MODIS 17A3HGF** (NPP) | 500m | 2026 when available | Yearly product |
| **MODIS 14A1** (Fire Daily) | 1km | 2026-05-01 to 2026-08-26 | Fire-season example |
| **MODIS 14A2** (Fire 8-day) | 1km | 2026-05-01 to 2026-08-26 | Fire-season example |
| **MODIS 10A1** (Snow) | 500m | 2026-02-01 to 2026-02-28 | Winter example |
| **MODIS 11A1** (Temperature) | 1km | 2026-05-01 to 2026-08-26 | Warm-season example |

---

## 💡 Example Queries That Work

### Ultra High-Resolution Imagery (0.6m - 10m)

**NAIP (0.6m aerial imagery)**
```
NAIP covers the United States and is not used for Canadian starter scenarios.
For Canadian high-resolution examples, use an MPC Pro tenant aerial collection,
such as 2026 before-and-after imagery over Jasper, Alberta.
```
💡 **Tip:** Use MPC Pro tenant collections when Canadian aerial coverage is required.

---

**Sentinel-2 L2A (10m multispectral)**
```
✅ "Show Sentinel-2 imagery over Toronto from 2026-06-01 to 2026-08-26 with low cloud cover"
✅ "Find Sentinel-2 images along the Mackenzie River from 2026-05-01 to 2026-06-30"
✅ "Display Sentinel-2 data for Halifax coastal monitoring from 2026-06-01 to 2026-08-26"
```
💡 **Tip:** Mention "recent" or "latest" - data is near real-time (last 30 days)

---

### High Resolution Imagery (30m)

**Landsat C2 L2**
```
✅ "Show Landsat imagery over Halifax from 2026-01-01 to 2026-08-26"
✅ "Find Landsat images of Toronto urban development from 2026-01-01 to 2026-08-26"
✅ "Display Landsat data for British Columbia forest monitoring from 2026-05-01 to 2026-08-26"
```
💡 **Tip:** Use "recent" for best results - data updated continuously

---

**HLS (Harmonized Landsat Sentinel-2)**
```
✅ "Show HLS images of Saskatchewan agricultural fields from 2026-04-01 to 2026-08-26"
✅ "Find HLS data for Alberta vegetation monitoring from 2026-05-01 to 2026-08-26 with low cloud cover"
✅ "Display HLS imagery of Manitoba wetlands from 2026-05-01 to 2026-08-26"
```
💡 **Tip:** HLS combines Landsat and Sentinel-2, use recent dates

---

### Elevation Data (30m - 90m)

**Copernicus DEM / NASADEM**
```
✅ "Show Copernicus DEM terrain around Banff for 2026 analysis"
✅ "Display terrain data for the North Shore Mountains in British Columbia"
✅ "Find topography along the Yukon River corridor"
✅ "Show a 3D elevation model of Cape Breton Island"
```
💡 **Tip:** No dates needed - these are static datasets from 2000-2021

---

### Radar/SAR Data (10m - 20m)

**Sentinel-1 RTC/GRD**
```
✅ "Show Sentinel-1 RTC over Vancouver from 2026-01-01 to 2026-08-26"
✅ "Find SAR data for Red River flood monitoring from 2026-03-01 to 2026-05-31"
✅ "Display Sentinel-1 for ship detection near Halifax from 2026-01-01 to 2026-08-26"
```
💡 **Tip:** Mention "recent" - radar data updated every 6-12 days

---

### MODIS Collections (250m - 1km)

**⚠️ IMPORTANT: Verify MODIS availability for the requested 2026 interval.**

**Surface Reflectance (MODIS 09A1 / 09Q1)**
```
✅ "Show MODIS surface reflectance over Saskatchewan from 2026-04-01 to 2026-08-26"
✅ "Find MODIS tiles over Manitoba from 2026-05-01 to 2026-08-26"
✅ "Display MODIS imagery of Quebec forests from 2026-04-01 to 2026-08-26"
```
💡 **Tip:** Specify exact 2026 start and end dates, then adjust if the collection reports an availability gap.

---

**Vegetation Indices (MODIS 13A1 / 13Q1 - NDVI)**
```
✅ "Show MODIS vegetation indices over Saskatchewan from 2026-04-01 to 2026-08-26"
✅ "Find MODIS NDVI for southern Alberta from 2026-05-01 to 2026-08-26"
✅ "Display vegetation health over Ontario cropland from 2026-04-01 to 2026-08-26"
```
💡 **Tip:** Use the Canadian growing-season interval from April through August 2026.

---

**Leaf Area Index (MODIS 15A2H)**
```
✅ "Show leaf area index over British Columbia from 2026-05-01 to 2026-08-26"
✅ "Find MODIS LAI for Quebec boreal forest from 2026-04-01 to 2026-08-26"
✅ "Display vegetation coverage in coastal British Columbia from 2026-05-01 to 2026-08-26"
```
💡 **Tip:** Best for tropical forests and dense vegetation areas

---

**Productivity (MODIS 17A2H GPP / 17A3HGF NPP)**
```
✅ "Show MODIS productivity over British Columbia from 2026-05-01 to 2026-08-26"
✅ "Find gross primary production over Saskatchewan cropland from 2026-04-01 to 2026-08-26"
✅ "Display ecosystem productivity in Quebec forests from 2026-04-01 to 2026-08-26"
```
💡 **Tip:** Focus on highly productive ecosystems (rainforests, croplands)

---

**Fire Detection (MODIS 14A1 / 14A2)**
```
✅ "Show MODIS fire data across Alberta from 2026-05-01 to 2026-08-26"
✅ "Find active fires in British Columbia from 2026-05-01 to 2026-08-26"
✅ "Display fire activity near Prince George from 2026-05-01 to 2026-08-26"
```
💡 **Tip:** Use the explicit Canadian fire-season range from May 1 through August 26, 2026.

---

**Snow Cover (MODIS 10A1)**
```
✅ "Show MODIS snow cover over Quebec from 2026-02-01 to 2026-02-28"
✅ "Find snow extent in Yukon from 2026-01-01 to 2026-03-31"
✅ "Display snow coverage around Banff from 2026-01-01 to 2026-03-31"
```
💡 **Tip:** Use Canadian winter months from January through March 2026.

---

**Land Surface Temperature (MODIS 11A1)**
```
✅ "Show MODIS temperature over Toronto from 2026-05-01 to 2026-08-26"
✅ "Find land surface temperature in Calgary from 2026-05-01 to 2026-08-26"
✅ "Display thermal data for Montreal urban heat islands from 2026-05-01 to 2026-08-26"
```
💡 **Tip:** Great for hot regions and urban heat analysis

---

## 🚫 Common Query Mistakes to Avoid

### ❌ Don't Use Vague Dates for MODIS
```
❌ "Show me recent MODIS data for Canada"  (Too broad to validate)
✅ "Show MODIS thermal anomalies across Alberta from 2026-05-01 to 2026-08-26"
```

### ❌ Don't Specify Dates for Static Datasets
```
❌ "Show 2026 elevation data around Banff"  (Elevation does not change)
✅ "Show Copernicus DEM terrain around Banff for 2026 analysis"
```

### ❌ Don't Use Old Dates for Near Real-Time Data
```
❌ "Show Sentinel-2 over Canada"  (Location and dates are underspecified)
✅ "Show Sentinel-2 imagery over Toronto from 2026-06-01 to 2026-08-26"
```

### ❌ Don't Use NAIP for Canadian Coverage
```
❌ "Show NAIP imagery over Jasper in 2026"  (NAIP covers the United States)
✅ "Show my MPC Pro aerial imagery over Jasper from 2026-01-01 to 2026-08-26"
```

---

## 📊 Collection Categories Summary

### Category 1: No Date Filter Needed
- **NAIP** - U.S.-only; use MPC Pro tenant imagery for Canadian aerial examples
- **All DEMs** - Static datasets (Copernicus 30m/90m, NASADEM)

### Category 2: Use Recent Dates (Last 30-90 Days)
- **Sentinel-2 L2A** - Last 30 days
- **Landsat C2 L2** - Last 90 days
- **HLS (L30/S30)** - Last 30 days
- **Sentinel-1 (RTC/GRD)** - Last 30-90 days

### Category 3: Use Explicit 2026 Ranges for MODIS
- **MODIS 09A1/09Q1** - Surface reflectance
- **MODIS 13A1/13Q1** - Vegetation indices (NDVI)
- **MODIS 15A2H** - Leaf area index
- **MODIS 17A2H** - Gross primary production
- **MODIS 17A3HGF** - Net primary production (yearly)
- **MODIS 14A1/14A2** - Fire detection
- **MODIS 11A1** - Land surface temperature

### Category 4: Seasonal Data (Winter 2026 for Snow)
- **MODIS 10A1** - Snow cover (use January through March 2026)

---

## 🎓 Pro Tips for Better Results

1. **For MODIS queries:** Specify an exact 2026 range and verify collection availability
2. **For optical imagery:** Mention "low cloud cover" or "clear sky" to filter cloudy scenes
3. **For elevation:** No need to specify dates - these are static datasets
4. **For Canadian aerial imagery:** Use an MPC Pro tenant collection because NAIP is U.S.-only
5. **For near real-time data:** Use an explicit 2026 interval so results are reproducible

---

## 🔍 Need Help?

If your query returns no results:
- **Check the date range** - Most issues are date-related
- **MODIS collections:** Verify that the requested 2026 interval is available
- **Elevation data:** Remove date filters
- **Canadian aerial imagery:** Use MPC Pro rather than NAIP
- **Optical imagery:** Use the catalog-backed 2026 ranges shown above

---

**Last Updated:** August 27, 2026
**Data Source:** Microsoft Planetary Computer STAC API  
**Validated Collections:** 21/21 (100% operational)
