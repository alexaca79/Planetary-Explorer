/** Return GeoFM map features, an empty list for a zero-result run, or null for unrelated responses. */
export function getGeoFmMapFeatures(response: any): any[] | null {
  const tools = Array.isArray(response?.tools_used) ? response.tools_used : [];
  const structured = response?.structured;
  const isGeoFm = tools.some((tool: string) => tool.includes('geofm'))
    || Boolean(structured?.compare_with_geofm)
    || Boolean(structured?.get_geofm_run)
    || Boolean(structured?.cancel_geofm_run)
    || Boolean(structured?.list_geofm_models);
  if (!isGeoFm) return null;
  const features = Array.isArray(response?.map_data?.features)
    ? response.map_data.features
    : [];
  return features.filter((feature: any) => feature?.geometry?.coordinates);
}