import { describe, expect, it } from 'vitest';

import { deriveChatLegend, legendForCollection } from '../chatLegend';

describe('chat legend derivation', () => {
  it('derives a radar legend from the STAC response collection', () => {
    const response = {
      data: {
        stac_results: {
          features: [{ collection: 'sentinel-1-rtc' }],
        },
      },
    };

    const legend = deriveChatLegend(response);

    expect(legend?.title).toBe('Radar backscatter');
    expect(legend?.items.map((item) => item.label)).toEqual(['Dark', 'Mid-tone', 'Bright']);
  });

  it('uses the exact resilience marker colours', () => {
    const legend = deriveChatLegend({
      isResilienceResponse: true,
      dossier: { facilities: [{ severity: 'severe' }] },
    });

    expect(legend?.items.map((item) => item.color)).toEqual([
      '#22c55e',
      '#eab308',
      '#f97316',
      '#dc2626',
    ]);
  });

  it('uses the exact PlanAura polygon colours for a completed GeoFM run', () => {
    const legend = deriveChatLegend({
      tools_used: ['get_geofm_run'],
      structured: {
        get_geofm_run: {
          success: true,
          structured: { status: 'complete', features: [{}] },
        },
      },
    });

    expect(legend?.title).toBe('PlanAura contextual change');
    expect(legend?.items.map((item) => item.color)).toEqual(['#ef4444', '#7f1d1d']);
    expect(legend?.items[0].description).toContain('above the requested threshold');
  });

  it.each(['denied', 'queued', 'failed'])(
    'keeps the HLS fire legend for a %s GeoFM request',
    (status) => {
      const legend = deriveChatLegend(
        {
          tools_used: ['compare_with_geofm'],
          structured: {
            compare_with_geofm: {
              success: status !== 'failed' && status !== 'denied',
              structured: { status },
            },
          },
        },
        {
          current_collection: 'hls2-s30',
          tile_urls: [{
            tilejson_url: 'https://example.test/item?assets=B12&assets=B8A&assets=B04',
          }],
        },
      );

      expect(legend?.title).toBe('HLS fire false colour');
    },
  );

  it('identifies scene-stretched HLS fire false colour from its tile URL', () => {
    const legend = deriveChatLegend({
      data: {
        stac_results: {
          features: [{ collection: 'hls2-s30' }],
        },
      },
      translation_metadata: {
        all_tile_urls: [{
          tilejson_url: 'https://example.test/item?assets=B12&assets=B8A&assets=B04',
        }],
      },
    });

    expect(legend?.title).toBe('HLS fire false colour');
    expect(legend?.note).toContain('B12/B8A/B04');
    expect(legend?.note).toContain('not official burn severity');
  });

  it('identifies HLS fire false colour from stable render-profile metadata', () => {
    const legend = deriveChatLegend({
      data: {
        stac_results: {
          features: [{ collection: 'hls2-s30' }],
        },
      },
      translation_metadata: {
        render_profile: { id: 'hls-s30-fire-false-colour' },
      },
    });

    expect(legend?.title).toBe('HLS fire false colour');
  });

  it.each([
    { sceneCount: 1, assets: ['B12', 'B8A', 'B04'], title: 'Sentinel-2 fire false colour' },
    { sceneCount: 2, assets: ['B12', 'B8A', 'B04'], title: 'Natural-colour imagery' },
    { sceneCount: 1, assets: ['B12A', 'B8AX', 'B04X'], title: 'Natural-colour imagery' },
    { sceneCount: 1, assets: ['B04', 'B8A', 'B12'], title: 'Natural-colour imagery' },
  ])('matches the selected Sentinel-2 source: %j', ({ sceneCount, assets, title }) => {
    const response = {
      data: {
        stac_results: {
          features: Array.from({ length: sceneCount }, (_, index) => ({
            id: `scene-${index}`, collection: 'sentinel-2-l2a',
          })),
        },
      },
      translation_metadata: {
        all_tile_urls: [{
          item_id: 'scene-0',
          tilejson_url: `https://example.test/item?${assets.map(asset => `assets=${asset}`).join('&')}`,
        }],
        mosaic_tilejson: {
          tilejson_url: 'https://example.test/mosaic?assets=B04&assets=B03&assets=B02',
        },
      },
    };

    const legend = deriveChatLegend(response);

    expect(legend?.title).toBe(title);
    if (title === 'Sentinel-2 fire false colour') {
      expect(legend?.note).toContain('B12/B8A/B04');
      expect(legend?.note).toContain('not official burn severity');
      expect(legend?.note).not.toContain('percentile');
    }
  });

  it('retains the Sentinel-2 fire legend from actual map context on a text follow-up', () => {
    const legend = deriveChatLegend({ response: 'Comparison complete.' }, {
      current_collection: 'sentinel-2-l2a',
      imagery_url: 'https://example.test/item?assets=B12&assets=B8A&assets=B04',
    });

    expect(legend?.title).toBe('Sentinel-2 fire false colour');
  });

  it('does not infer the fire profile from partial asset-name matches', () => {
    const legend = deriveChatLegend({
      data: {
        stac_results: {
          features: [{ collection: 'hls2-s30' }],
        },
      },
      translation_metadata: {
        all_tile_urls: [{
          tilejson_url: 'https://example.test/item?assets=B12A&assets=B8AX&assets=B04X',
        }],
      },
    });

    expect(legend?.title).toBe('Natural-colour imagery');
  });

  it('describes a fire false-colour background under PlanAura polygons', () => {
    const legend = deriveChatLegend(
      {
        tools_used: ['get_geofm_run'],
        structured: {
          get_geofm_run: {
            success: true,
            structured: { status: 'complete', features: [{}] },
          },
        },
      },
      {
        current_collection: 'hls2-s30',
        tile_urls: [{
          tilejson_url: 'https://example.test/item?assets=B12&assets=B8A&assets=B04',
        }],
      },
    );

    expect(legend?.title).toBe('PlanAura contextual change');
    expect(legend?.note).toContain('fire false-colour composite');
  });

  it('derives a productivity legend for the Canadian MODIS GPP collection', () => {
    const legend = legendForCollection('modis-17A2H-061');

    expect(legend?.title).toBe('Vegetation productivity');
  });

  it('does not invent a legend for an unknown text-only collection', () => {
    expect(legendForCollection('unknown-text-result')).toBeUndefined();
  });
});