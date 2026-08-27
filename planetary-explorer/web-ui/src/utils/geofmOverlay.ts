/** Geointelligence modules whose responses paint the GeoFM vector overlay. */
export const GEOFM_MODULES = ['foundation_change', 'classification'] as const;

export type GeoFmModule = typeof GEOFM_MODULES[number];

/** Fallback fill used by contextual-change runs, which have no per-class palette. */
export const GEOFM_CHANGE_FILL = '#ef4444';

/** Fallback outline used by contextual-change runs. */
export const GEOFM_CHANGE_OUTLINE = '#7f1d1d';

export interface GeoFmClassLegendEntry {
  value: number;
  name: string;
  colour: string;
  areaKm2: number | null;
  percentOfClassified: number | null;
  meanConfidence: number | null;
}

export interface GeoFmClassLegend {
  schemeId: string;
  entries: GeoFmClassLegendEntry[];
}

/** Return GeoFM map features, an empty list for a zero-result run, or null for unrelated responses. */
export function getGeoFmMapFeatures(response: any): any[] | null {
  const tools = Array.isArray(response?.tools_used) ? response.tools_used : [];
  const structured = response?.structured;
  const isGeoFm = tools.some((tool: string) => tool.includes('geofm'))
    || Boolean(structured?.compare_with_geofm)
    || Boolean(structured?.classify_with_geofm)
    || Boolean(structured?.get_geofm_run)
    || Boolean(structured?.cancel_geofm_run)
    || Boolean(structured?.list_geofm_models)
    || Boolean(structured?.list_geofm_class_schemes);
  if (!isGeoFm) return null;
  const features = Array.isArray(response?.map_data?.features)
    ? response.map_data.features
    : [];
  return features.filter((feature: any) => feature?.geometry?.coordinates);
}

/**
 * Return the categorical legend for a completed classification run, or null.
 *
 * Only a run that reports its class-scheme id produces a legend: a class name
 * without its published scheme is not a result we are willing to render.
 */
export function getGeoFmClassLegend(response: any): GeoFmClassLegend | null {
  const structured = response?.structured;
  if (!structured || typeof structured !== 'object') return null;
  for (const toolName of ['classify_with_geofm', 'get_geofm_run', 'retry_geofm_run']) {
    const statistics = structured[toolName]?.structured?.statistics;
    const schemeId = statistics?.class_scheme_id;
    if (typeof schemeId !== 'string' || schemeId.length === 0) continue;
    const classes = Array.isArray(statistics?.classes) ? statistics.classes : [];
    const entries = classes
      .filter((entry: any) => entry && typeof entry === 'object')
      .map((entry: any) => ({
        value: Number(entry.class_value),
        name: String(entry.class_name ?? ''),
        colour: String(entry.class_colour ?? entry.colour_hex ?? GEOFM_CHANGE_FILL),
        areaKm2: numberOrNull(entry.area_km2),
        percentOfClassified: numberOrNull(entry.percent_of_classified),
        meanConfidence: numberOrNull(entry.mean_confidence),
      }))
      .filter((entry: GeoFmClassLegendEntry) => Number.isFinite(entry.value) && entry.name !== '');
    if (entries.length === 0) continue;
    return { schemeId, entries };
  }
  return null;
}

/** Return a feature's class colour, falling back to the contextual-change palette. */
export function getGeoFmFeatureFill(feature: any): string {
  const colour = feature?.properties?.class_colour;
  return isHexColour(colour) ? colour : GEOFM_CHANGE_FILL;
}

/** Return a feature's outline colour, derived from its class colour when present. */
export function getGeoFmFeatureOutline(feature: any): string {
  const colour = feature?.properties?.class_colour;
  return isHexColour(colour) ? colour : GEOFM_CHANGE_OUTLINE;
}

export function isHexColour(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value);
}

function numberOrNull(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
