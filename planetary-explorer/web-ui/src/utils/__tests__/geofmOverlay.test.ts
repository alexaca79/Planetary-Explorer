import { describe, expect, it } from 'vitest';

import {
  GEOFM_MODULES,
  getGeoFmClassLegend,
  getGeoFmFeatureFill,
  getGeoFmFeatureOutline,
  getGeoFmMapFeatures,
} from '../geofmOverlay';

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

  it('recognises a classification submission', () => {
    const feature = {
      type: 'Feature',
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [0, 0]]] },
      properties: { class_value: 1 },
    };
    expect(getGeoFmMapFeatures({
      structured: { classify_with_geofm: { structured: { status: 'queued' } } },
      map_data: { type: 'FeatureCollection', features: [feature] },
    })).toEqual([feature]);
  });
});

describe('GEOFM_MODULES', () => {
  it('covers both GeoFM-backed modules', () => {
    expect([...GEOFM_MODULES]).toEqual(['foundation_change', 'classification']);
  });
});

describe('getGeoFmClassLegend', () => {
  const legendResponse = (schemeId: string) => ({
    structured: {
      get_geofm_run: {
        structured: {
          status: 'complete',
          statistics: {
            class_scheme_id: schemeId,
            classes: [
              {
                class_value: 1,
                class_name: 'Water-like',
                class_colour: '#2b6cb0',
                area_km2: 4.25,
                percent_of_classified: 31.5,
                mean_confidence: 0.82,
              },
              {
                class_value: 2,
                class_name: 'Vegetation-like',
                class_colour: '#276749',
                area_km2: 9.25,
                percent_of_classified: 68.5,
                mean_confidence: 0.64,
              },
            ],
          },
        },
      },
    },
  });

  it('returns null for a response without classification statistics', () => {
    expect(getGeoFmClassLegend({ structured: { get_geofm_run: { structured: {} } } })).toBeNull();
  });

  it('returns null when the run omits its class scheme id', () => {
    const response = legendResponse('');
    expect(getGeoFmClassLegend(response)).toBeNull();
  });

  it('returns every class with its share and confidence', () => {
    expect(getGeoFmClassLegend(legendResponse('planaura_unsupervised_v1'))).toEqual({
      schemeId: 'planaura_unsupervised_v1',
      entries: [
        {
          value: 1,
          name: 'Water-like',
          colour: '#2b6cb0',
          areaKm2: 4.25,
          percentOfClassified: 31.5,
          meanConfidence: 0.82,
        },
        {
          value: 2,
          name: 'Vegetation-like',
          colour: '#276749',
          areaKm2: 9.25,
          percentOfClassified: 68.5,
          meanConfidence: 0.64,
        },
      ],
    });
  });

  it('drops classes that have no published name', () => {
    const response = legendResponse('planaura_unsupervised_v1');
    response.structured.get_geofm_run.structured.statistics.classes[0].class_name = '';
    const legend = getGeoFmClassLegend(response);
    expect(legend?.entries.map((entry) => entry.name)).toEqual(['Vegetation-like']);
  });
});

describe('GeoFM feature colours', () => {
  it('uses the published class colour when a feature carries one', () => {
    const feature = { properties: { class_colour: '#2b6cb0' } };
    expect(getGeoFmFeatureFill(feature)).toBe('#2b6cb0');
    expect(getGeoFmFeatureOutline(feature)).toBe('#2b6cb0');
  });

  it('falls back to the change palette for contextual-change features', () => {
    const feature = { properties: { mean_distance: 0.7 } };
    expect(getGeoFmFeatureFill(feature)).toBe('#ef4444');
    expect(getGeoFmFeatureOutline(feature)).toBe('#7f1d1d');
  });

  it('rejects a non-hex colour rather than injecting it into a style', () => {
    const feature = { properties: { class_colour: 'url(javascript:alert(1))' } };
    expect(getGeoFmFeatureFill(feature)).toBe('#ef4444');
  });
});
