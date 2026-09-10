interface NbrSample {
  acquisition_datetime: string;
  item_id: string;
  valid_pixel_count: number;
  total_pixel_count: number;
  valid_pixel_fraction: number;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNbrSample(sample: any): sample is NbrSample {
  return typeof sample?.acquisition_datetime === 'string'
    && Number.isFinite(Date.parse(sample.acquisition_datetime))
    && typeof sample.item_id === 'string'
    && /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(sample.item_id)
    && Number.isInteger(sample.valid_pixel_count)
    && Number.isInteger(sample.total_pixel_count)
    && sample.total_pixel_count > 0
    && sample.valid_pixel_count > 0
    && sample.valid_pixel_count <= sample.total_pixel_count
    && isFiniteNumber(sample.valid_pixel_fraction)
    && sample.valid_pixel_fraction > 0
    && sample.valid_pixel_fraction <= 1;
}

function formatSample(label: string, requested: string, value: number, sample: NbrSample): string[] {
  const acquired = new Date(sample.acquisition_datetime).toISOString().slice(0, 10);
  const dateNote = acquired === requested ? '' : '; substituted date';
  const itemUrl = `https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/${encodeURIComponent(sample.item_id)}`;
  return [
    `**${label}**`,
    `- **Acquired:** \`${acquired}\` (requested \`${requested}\`${dateNote})`,
    `- **Mean NBR:** \`${value.toFixed(4)}\``,
    `- **Valid pixels:** ${sample.valid_pixel_count} / ${sample.total_pixel_count} (${(sample.valid_pixel_fraction * 100).toFixed(1)}%)`,
    `- **Scene:** [${sample.item_id}](${itemUrl})`,
    '',
  ];
}

export function formatTemporalNbrResponse(response: any): string | undefined {
  const tools = response?.tools_used;
  const result = response?.structured?.compare_temporal;
  if (!Array.isArray(tools) || tools.length === 0 || tools.some(tool => tool !== 'compare_temporal')
    || result?.success !== true || result.metric !== 'nbr' || result.collection !== 'sentinel-2-l2a'
    || !isFiniteNumber(result.t1_value) || !isFiniteNumber(result.t2_value)
    || !isNbrSample(result.t1_sample) || !isNbrSample(result.t2_sample)
    || typeof result.t1 !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(result.t1)
    || typeof result.t2 !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(result.t2)) {
    return undefined;
  }

  const difference = result.t1_value - result.t2_value;
  if (!Number.isFinite(difference)) return undefined;
  const signed = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(4)}`;
  const lines = [
    '**NBR Comparison**',
    '',
    `**Before minus after (dNBR):** \`${signed(difference)}\``,
    '',
    `**After minus before:** \`${signed(-difference)}\``,
    '',
    ...formatSample('Before', result.t1, result.t1_value, result.t1_sample),
    ...formatSample('After', result.t2, result.t2_value, result.t2_sample),
  ];
  if (Array.isArray(result.bbox) && result.bbox.length === 4 && result.bbox.every(isFiniteNumber)) {
    lines.push(`**Analysis bbox:** \`[${result.bbox.map((coordinate: number) => coordinate.toFixed(5)).join(', ')}]\``, '');
  }
  lines.push(
    'Each mean uses independently valid pixels. Different cloud and no-data masks can cover different areas. This is not a shared-pixel burn-severity map or a measurement of burned hectares.',
    '',
    '**Data source:** Public Planetary Computer (`sentinel-2-l2a`).',
  );
  return lines.join('\n');
}