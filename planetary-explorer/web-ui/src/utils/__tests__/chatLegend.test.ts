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

  it('does not invent a legend for an unknown text-only collection', () => {
    expect(legendForCollection('unknown-text-result')).toBeUndefined();
  });
});