---
title: Wildfire burn-scar assessment mock for September 2026
description: A pin-based Canadian wildfire demonstration using recent catalog scenes, CPU imagery and NBR comparison, with explicit cloud and interpretation limits.
ms.date: 2026-09-09
ms.topic: how-to
keywords:
  - wildfire
  - burn scar
  - Sentinel-2
  - NBR
  - demonstration
---

## Live Run And Photos

For shared controls and current pin behavior, start with the
[application usage guide](get-started-playbook.md). Its
[Web Search and Code Interpreter example](get-started-playbook.md#use-web-search-and-code-interpreter)
uses the archived observations below to demonstrate research and calculation
without claiming new satellite measurements.

The September 9 trial is recorded in [photos and live results](wildfire-burn-scar-results.md).
It includes natural-colour and fire-colour source images for June 1, August 28,
September 2 and September 7, plus actual NBR outputs. The CPU calculation
worked. After the initial display failure, a frontend correction was deployed
and verified with the August 28 fire-colour layer and correctly signed NBR
data in chat. Official-status interpretation and sufficient comparable clear
coverage remain unverified; this is not a complete burn-severity workflow.

The later [BC pin investigation](wildfire-burn-scar-results.md#canadian-pin-follow-up)
also fixed imagery routing, viewport leakage and nearest-date selection in the
deployed API. Use the [Canadian-pin workflow](#use-any-canadian-pin) below to
repeat the imagery request away from the Ontario demo coordinates.

## Scenario

On September 8, 2026, a forestry analyst receives a request to assess forest
change around a reported wildfire location in Thunder Bay District, Ontario.
The team has a coordinate but no confirmed local burn boundary. They need
evidence for planning a follow-up survey, not an evacuation or fire-control
decision.

> A fire affected forest near latitude 50.2680, longitude -89.8572. Show
> suspected burn scars using recent imagery, compare vegetation with a
> pre-fire baseline, and explain where clouds or other changes prevent a
> reliable conclusion. Do not label every changed pixel as burned.

The point comes from the existing [Thunder Bay 36 case study](geofm-thunder-bay-fire.md).
The September assessment is a mock scenario, not a claim that a new fire
started there in September or that the incident is still active. Confirm the
incident timeline with official sources before interpreting the comparison.

> [!IMPORTANT]
> The original mock was based on catalog entries only. New source previews and
> CPU NBR measurements are now recorded separately in the live-results page,
> together with the failed trial and verified frontend follow-up. No burn boundary, burned-area
> estimate or GPU result is claimed. The July case study's measurements and
> screenshots must not be presented as results for the newer dates.

## Dates And Available Imagery

Keep the June baseline to provide pre-event context. Moving both dates into
September could measure post-fire recovery or another change instead of the
fire's effect.

| Input                  | Value                                                       |
| ---------------------- | ----------------------------------------------------------- |
| Assessment date        | September 8, 2026                                            |
| Analysis point         | 50.2680, -89.8572, WGS84 latitude then longitude               |
| Baseline target        | June 1, 2026; verify a usable pre-fire Sentinel-2 observation  |
| Recent epoch requested | September 7, 2026                                            |
| Display candidate      | August 28, 2026; 87.8% NBR-valid in the fixed source-test bbox |
| CPU numeric collection | sentinel-2-l2a                                               |
| Initial scope          | A small area around the pin, not the entire wildfire         |

A Public Planetary Computer lookup at the point, covering August 25 through
September 8, returned these Sentinel-2 observations. The lookup completed at
2026-09-09 03:49 UTC; its observation cutoff remained September 8. No further
catalog page was returned for the queried collections and interval.

| Acquisition Date | Scene Cloud Cover | Role In The Mock                                  |
| ---------------- | ----------------- | ------------------------------------------------- |
| September 7      | 99.87%            | Newest returned scene; assess cloud obstruction    |
| September 2      | 89.52%            | Another recent candidate with substantial cloud    |
| August 28        | 30.74%            | Earlier candidate for local pixel-quality review   |

Exact catalog records:

- [September 7 Sentinel-2 item](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2C_MSIL2A_20260907T165841_R069_T15UYR_20260907T215814)
- [September 2 Sentinel-2 item](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2B_MSIL2A_20260902T165849_R069_T15UYR_20260902T222832)
- [August 28 Sentinel-2 item](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2C_MSIL2A_20260828T165841_R069_T15UYR_20260828T215915)

Scene cloud percentage describes the whole scene, not the pinned patch.
Neither the newest date nor the lowest percentage proves that the requested
area is usable. Inspect local quality masks and valid-pixel coverage. The
recent HLS S30 lookup returned a September 2 item with 100% scene cloud cover,
so the original HLS/PlanAura workflow is not assumed ready for these dates.

## Use Any Canadian Pin

Use this workflow for a dropped Canadian pin instead of copying the Ontario
coordinates in the walkthrough. It loads imagery; it does not establish that
a wildfire occurred at the selected location.

1. Drop a pin on the map and confirm the displayed latitude and longitude.
  Use ordinary chat with the public catalog, not the Foundation Change module.
2. Request the nearest observation to your target date:

  ```text
  Show collection sentinel-2-l2a fire false-colour imagery at point closest to 2026-08-28.
  ```

3. Check the actual acquisition date in the reply. Open **Map layers**, confirm
  the Sentinel-2 layer is visible, and use its opacity control to inspect it.
  The fire-colour legend must identify B12/B8A/B04. A layer entry without
  visible imagery is not a successful display.
4. For measurements, continue with the CPU NBR prompt in step 3 of the
  walkthrough. Check both actual sampling dates and valid-pixel coverage;
  the calculation can select different scenes from the displayed image.

`Closest to` searches within 14 days either side of the requested date,
ending no later than the current date. An exact request using `on 2026-08-28`
stays exact. If that day has no scene, follow the imagery request with:

```text
Find the date that has it please closest to that date.
```

The follow-up retains the previous user imagery request and uses the current
pin, including after moving it. A missing exact-day observation is not proof
that the surrounding area lacks coverage. Nearest does not mean cloud-free.

### BC Failure And Correction

At `49.432296, -122.482823`, the app incorrectly sent an imagery-display request
to Temporal compare, then required one scene to cover the entire zoom-9
viewport. Its generated reply described that extent failure as missing data.
August 27 and August 29 scenes actually covered the pin.

The September 9 API correction routes explicit point imagery to loading and
keeps the pin authoritative. Imagery uses a one-mile-radius extent independent
of zoom; ordinary point NBR uses a 60 m window. Explicit analysis bboxes, area
requests and specialist modules retain their requested extent. The live BC
follow-up displayed August 29, rather than mislabelling it August 28.

Verification passed at 19 Canadian locations across all provinces and
territories, with 1,410 backend tests passing and one existing skip. The BC
browser check recorded 42 successful tile responses and a visible overlay.
See the [full results](wildfire-burn-scar-results.md#canadian-pin-follow-up) for
scene identifiers, measurements and deployment evidence.

> [!IMPORTANT]
> This is a general point-handling correction, not a guarantee of clear imagery
> at every point or date. Clouds, snow, acquisition schedules and genuine data
> gaps still apply. The BC scene had 69.57% whole-scene cloud cover. Check local
> visibility before interpreting any colour change as a suspected burn scar.

## Demo Walkthrough

### 1. Establish The Incident Context

Use ordinary chat to request corroborating public information:

```text
Search the web for official Ontario and NRCan information relevant to the
reported wildfire near latitude 50.2680, longitude -89.8572. Give source
links and publication dates. Distinguish incident dates, imagery dates and
the September 8, 2026 assessment date. Do not assume this is the City of
Thunder Bay or invent a current incident status.
```

Web Search must be enabled and connected. Use the
[deployment prerequisites](deployment.md#private-data-and-other-integrations) for its service
configuration. Retrieved incident reports corroborate context; they do not
prove that a particular satellite pixel burned.

### 2. Inspect The Recent Display Candidate

Start with the August 28 scene for the visual portion:

```text
Show collection sentinel-2-l2a fire false-colour imagery at latitude
50.2680 and longitude -89.8572 on 2026-08-28.
```

Use this load-only request first. Combining the load with a metadata analysis
has intermittently produced a clarification instead of imagery. Ask for source
metadata separately after confirming the layer appears. In a browser tab that
predates the September 9 correction, finish any draft before refreshing.

Confirm the collection is `sentinel-2-l2a`, the item matches the August 28
catalog record, and the map is at the district location. Drop a pin at the
coordinate. Keep the view local and record the actual analysis extent.
Stop if another date, location or collection is loaded without disclosure.

Use the fire/burn-scar display and layer-opacity controls to inspect the
surface. Red or rust colours can suggest affected vegetation, but dry ground,
clearing and display stretches can produce similar appearances. Dark pixels
can be water, shadow or missing data. A screenshot alone is not a burn map.

For the tougher case, request the September 7 scene next. A satisfactory
response must acknowledge its high scene cloud cover and withhold a local
assessment unless usable pixels are established. Do not assume a fully
automatic cloud warning or fallback selection is implemented in the UI.

### 3. Request A CPU Burn-Index Comparison

Keep the pin set and use ordinary chat, not the single-date Raster Analysis
button or Foundation Change module:

```text
At the pinned location, use compare_temporal with collection sentinel-2-l2a,
t1 2026-06-01, t2 2026-09-07 and metric nbr. Report the actual acquisition
dates, scene IDs, analysis bbox, valid-pixel coverage, mean NBR for each
epoch and dNBR. Explain any substituted dates. Do not use PlanAura or
submit GPU work. Do not classify burn severity or claim burned hectares.
```

Normalized Burn Ratio (NBR) compares near-infrared and shortwave-infrared
reflectance. The current tool reports `dnbr` as mean NBR before minus mean
NBR after. A positive value can support evidence of vegetation disturbance;
it does not establish the cause or a severity class by itself.

The tool searches within 14 days either side of each requested day and may
prefer another usable scene. September 7 is a requested epoch, not a guarantee
that the September 7 image is sampled. If the selected later scene predates
August 25, it does not meet this mock's recent-observation requirement. Mark
that run inconclusive instead of presenting it as a September measurement.
Both actual dates must bracket the relevant fire effects.

An explicit analysis bbox takes precedence. After the
[Canadian pin correction](wildfire-burn-scar-results.md#canadian-pin-follow-up),
ordinary requests at the pinned location use a 60 m window rather than the
passive viewport bounds. Explicit area and specialist-module requests retain
their extent. Confirm the returned spatial support before describing a result
as point-scale or area-wide. The June baseline in
the older case study used HLS; do not copy its NBR values into this separate
Sentinel-2 comparison.

### 4. Present A Qualified Assessment

The scripted response below is a mock response format, not measured output:

> Assessment dated September 8, 2026. The latest returned scene was acquired
> on September 7 and has high scene-level cloud cover. The August 28 scene is
> a fallback candidate, pending local quality checks. A burn-scar conclusion
> requires usable observations before and after the incident. Report the
> actual dates and measured NBR change when available; otherwise mark the
> result inconclusive. No burned-area or severity estimate has been produced.

For a completed live demo, record the point, bbox, both source links and
actual dates, mean NBR values, `dnbr`, valid-pixel fractions, and alternative
explanations. Each epoch is summarized independently, so the difference is
not a pixelwise dNBR raster over one shared valid mask. Do not convert it to
burned hectares or label a layer as an official fire perimeter.

For the [verified layer-and-data follow-up](wildfire-burn-scar-results.md#deployed-layer-and-data-fix),
the same comparison prompt used `t2 2026-08-28`. The map displayed August 28,
but the sampler selected August 20 with only 26.7% valid later pixels and
returned `dnbr +0.1239` for its viewport. That result demonstrates the CPU
workflow and date disclosure; it does not meet the recent-observation criterion.

## Optional Change Polygons

PlanAura can add contextual-change polygons only after compatible, sufficiently
clear HLS observations and the pinned area pass its preflight. Follow the
[Foundation Change approval procedure](geofm-foundation-change.md). The recent
Sentinel-2 scene IDs above are not HLS inputs for that workflow.

Approval starts billed GPU work. It is outside the CPU mock. Returned polygons
show model-detected change, not a validated wildfire boundary. Do not reuse an
older run's polygons or area as evidence for the September assessment.

## Acceptance Checks

- [x] Recent candidate dates and source IDs were read from the public catalog
- [x] September cloud obstruction and actual-date reporting are explicit
- [x] August 28 imagery loads at the correct point with its actual display bands
- [ ] Local quality checks establish usable pixels for both selected epochs
- [ ] Actual acquisition dates bracket fire effects and meet the recent-date requirement
- [x] NBR comparison returns numeric evidence or an explicit inconclusive result
- [x] Standalone successful NBR chat displays numeric evidence with both sign conventions
- [ ] Official incident sources are checked and cited for the assessment
- [ ] Any requested GPU run receives separate approval and produces new evidence

The live API comparison substituted September 2 for September 7 and used only
12.6% valid later pixels; it is not a passing whole-area assessment. Exact-date
sampling found 87.8% validity on August 28 and none on September 7. Official map
links were retrieved, but the incident-specific narrative remains unverified.

A failed quality check is a valid inconclusive assessment, not evidence that
there was no burning. Automated pixelwise burn-scar segmentation, calibrated
severity classes and a validated burned-area estimate remain additional work.