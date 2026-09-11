import { describe, expect, it } from 'vitest';
import { formatTemporalNbrResponse } from '../temporalNbr';

function createResponse() {
  return {
    tools_used: ['compare_temporal'],
    response: 'Generated answer',
    structured: {
      compare_temporal: {
        success: true,
        metric: 'nbr',
        collection: 'sentinel-2-l2a',
        t1: '2026-06-01',
        t2: '2026-08-28',
        t1_value: 0.2,
        t2_value: 0.1,
        bbox: [-89.8672, 50.258, -89.8472, 50.278],
        t1_sample: {
          acquisition_datetime: '2026-06-01T17:07:11Z',
          item_id: 'S2A_BEFORE',
          valid_pixel_count: 100,
          total_pixel_count: 100,
          valid_pixel_fraction: 1,
        },
        t2_sample: {
          acquisition_datetime: '2026-08-20T17:07:11Z',
          item_id: 'S2A_AFTER',
          valid_pixel_count: 27,
          total_pixel_count: 100,
          valid_pixel_fraction: 0.27,
        },
      },
    },
  };
}

describe('formatTemporalNbrResponse', () => {
  it.each([
    [0.2, 0.1, '+0.1000', '-0.1000'],
    [0.1, 0.2, '-0.1000', '+0.1000'],
    [0, 0, '+0.0000', '+0.0000'],
  ])('labels both conventions for %s before and %s after', (before, after, difference, change) => {
    const response = createResponse();
    Object.assign(response.structured.compare_temporal, { t1_value: before, t2_value: after });

    const text = formatTemporalNbrResponse(response);

    expect(text).toContain(`**Before minus after (dNBR):** \`${difference}\``);
    expect(text).toContain(`**After minus before:** \`${change}\``);
    expect(text).not.toContain(response.response);
  });

  it('includes actual dates, coverage, bbox, scene links and independent-mask limitations', () => {
    const text = formatTemporalNbrResponse(createResponse());

    expect(text).toContain('`2026-08-20` (requested `2026-08-28`; substituted date)');
    expect(text).toContain('27 / 100 (27.0%)');
    expect(text).toContain('[-89.86720, 50.25800, -89.84720, 50.27800]');
    expect(text).toContain('https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/S2A_AFTER');
    expect(text).toContain('independently valid pixels');
    expect(text).toContain('not a shared-pixel burn-severity map');
  });

  it('does not label exact acquisitions as substituted', () => {
    const response = createResponse();
    response.structured.compare_temporal.t2_sample.acquisition_datetime = '2026-08-28T17:07:11Z';

    expect(formatTemporalNbrResponse(response)).not.toContain('substituted');
  });

  it.each([
    { success: false },
    { metric: 'ndvi' },
    { collection: 'hls2-s30' },
    { t1_value: Number.NaN },
    { t2_value: Number.POSITIVE_INFINITY },
    { t1_value: '0.2' },
    { t2_sample: null },
    { t2: undefined },
  ])('leaves unsupported or incomplete results unchanged: %j', (overrides) => {
    const response = createResponse();
    Object.assign(response.structured.compare_temporal, overrides);

    expect(formatTemporalNbrResponse(response)).toBeUndefined();
  });

  it.each([
    { acquisition_datetime: 'invalid' },
    { item_id: '[untrusted](https://example.com)' },
    { valid_pixel_fraction: 2 },
    { valid_pixel_count: 0 },
    { valid_pixel_count: 101 },
    { total_pixel_count: 0 },
  ])('does not invent valid sample metadata: %j', (overrides) => {
    const response = createResponse();
    Object.assign(response.structured.compare_temporal.t2_sample, overrides);

    expect(formatTemporalNbrResponse(response)).toBeUndefined();
  });

  it('preserves responses that combine other tools', () => {
    const response = createResponse();
    response.tools_used.push('web_search');

    expect(formatTemporalNbrResponse(response)).toBeUndefined();
  });

  it.each([null, undefined, 'Plain text', {}])('leaves ordinary responses unchanged: %j', (response) => {
    expect(formatTemporalNbrResponse(response)).toBeUndefined();
  });
});