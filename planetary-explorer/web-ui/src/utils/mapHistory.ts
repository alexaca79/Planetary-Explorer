import { ChatHistoryContext, MapContext } from '../services/api';
import type { TileJsonFetchOptions, TileJsonResult } from './tileJsonFetcher';

const RESTORABLE_MODULES = new Set([
  'building_damage',
  'extreme_weather',
  'forecast',
  'foundation_change',
  'resilience',
  'site_audit',
  'terrain',
  'timeseries',
  'vision',
]);

export function restorableHistoryModule(module?: string): string | null {
  return module && RESTORABLE_MODULES.has(module) ? module : null;
}

export function restoredLayerFromContext(map?: Partial<MapContext>): any | null {
  if (!map) return null;
  const savedTiles = map.tile_urls?.filter(
    (tile) => Boolean(tile.tilejson_url) && !tile.tilejson_url.includes('<redacted>'),
  ) || [];
  const fallbackTile = savedTiles[0];
  const imageryUrl = map.imagery_url?.includes('<redacted>')
    ? undefined
    : map.imagery_url;
  const tileUrl = fallbackTile?.tilejson_url || imageryUrl;
  if (!tileUrl) return null;
  const bounds = map.bounds
    ? [map.bounds.west, map.bounds.south, map.bounds.east, map.bounds.north]
    : undefined;
  const collection = map.current_collection || fallbackTile?.collection || 'restored-layer';
  const itemId = map.item_id || fallbackTile?.item_id || 'restored-item';
  const tileBounds = bounds || [-180, -85, 180, 85];
  const items = savedTiles.length > 0
    ? savedTiles.map((tile, index) => ({
        id: tile.item_id || `${itemId}-${index + 1}`,
        collection: tile.collection || collection,
        bbox: tile.bbox,
        datetime: map.datetime || '',
        tile_url: tile.tilejson_url,
      }))
    : [{
        id: itemId,
        collection,
        datetime: map.datetime || '',
        tile_url: tileUrl,
      }];
  const allTileUrls = savedTiles.map((tile, index) => ({
      item_id: tile.item_id || `${itemId}-${index + 1}`,
      bbox: tile.bbox || tileBounds,
      tilejson_url: tile.tilejson_url,
    }));
  return {
    bbox: bounds,
    items,
    tile_url: tileUrl,
    preview_url: tileUrl,
    all_tile_urls: allTileUrls.length > 0 ? allTileUrls : undefined,
  };
}

export interface ChatHistoryMapRestore {
  token: number;
  context: ChatHistoryContext;
}

interface LeafletTileData {
  bbox?: number[];
  tile_url?: string;
  all_tile_urls?: Array<{
    tilejson_url: string;
    bbox?: number[];
  }>;
}

export async function resolveLeafletTileSources(
  data: LeafletTileData,
  collection: string,
  fetchTileJson: (
    url: string,
    options: TileJsonFetchOptions,
  ) => Promise<TileJsonResult>,
): Promise<Array<{ tileTemplate: string; bbox?: number[] }>> {
  const sources = data.all_tile_urls?.length
    ? data.all_tile_urls.map((tile) => ({
        url: tile.tilejson_url,
        bbox: tile.bbox,
      }))
    : data.tile_url
      ? [{ url: data.tile_url, bbox: data.bbox }]
      : [];

  const resolved = await Promise.all(sources.map(async (source) => {
    if (
      source.url.includes('{z}') &&
      source.url.includes('{x}') &&
      source.url.includes('{y}')
    ) {
      return { tileTemplate: source.url, bbox: source.bbox };
    }
    const result = await fetchTileJson(source.url, { collection });
    return result.success && result.tileTemplate
      ? { tileTemplate: result.tileTemplate, bbox: source.bbox || result.tilejson?.bounds }
      : null;
  }));

  return resolved.filter(
    (source): source is { tileTemplate: string; bbox?: number[] } => source !== null,
  );
}

export function buildExpansionSearchBody(
  collection: string,
  bbox: number[],
  stacMode: 'public' | 'pro' = 'public',
) {
  return {
    collections: [collection],
    bbox,
    limit: 50,
    sortby: [{ field: 'datetime', direction: 'desc' }],
    stac_mode: stacMode,
  };
}