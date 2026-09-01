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
        get_geofm_run: { structured: { status: 'complete', features: [{}] } },
      },
    });

    expect(legend?.title).toBe('PlanAura contextual change');
    expect(legend?.items.map((item) => item.color)).toEqual(['#ef4444', '#7f1d1d']);
    expect(legend?.items[0].description).toContain('above the requested threshold');
  });

  it('derives a productivity legend for the Canadian MODIS GPP collection', () => {
    const legend = legendForCollection('modis-17A2H-061');

    expect(legend?.title).toBe('Vegetation productivity');
  });

  it('does not invent a legend for an unknown text-only collection', () => {
    expect(legendForCollection('unknown-text-result')).toBeUndefined();
  });
});