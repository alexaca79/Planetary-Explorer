import { describe, expect, it } from 'vitest';

import { getGeoFmMapFeatures } from '../geofmOverlay';

describe('getGeoFmMapFeatures', () => {
  it('returns null for unrelated responses', () => {
    expect(getGeoFmMapFeatures({ tools_used: ['sample_raster_value'] })).toBeNull();
  });

  it('returns an empty list for a GeoFM run with no detected changes', () => {
    expect(getGeoFmMapFeatures({
      tools_used: ['get_geofm_run'],
      map_data: null,
    })).toEqual([]);
  });

  it('returns valid features from a completed GeoFM run', () => {
    const feature = {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [0, 0]]] },
      properties: {},
    };
    expect(getGeoFmMapFeatures({
      structured: { get_geofm_run: { structured: { status: 'complete' } } },
      map_data: { type: 'FeatureCollection', features: [feature] },
    })).toEqual([feature]);
  });
});