import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { chromium } from '../planetary-explorer/web-ui/node_modules/playwright/index.mjs';

const { values } = parseArgs({
  options: {
    'base-url': { type: 'string', default: 'http://127.0.0.1:5173' },
    'output-dir': { type: 'string' },
    help: { type: 'boolean', default: false },
  },
});

if (values.help) {
  console.log('Usage: node scripts/verify_map_loading.mjs [--base-url URL] [--output-dir PATH]');
  console.log('Checks the real public fallback map, tiles, zoom, and pins without AI analysis.');
  process.exit(0);
}

const target = new URL(values['base-url']);
if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)) {
  throw new Error('Map fallback verification requires a loopback URL.');
}
const outputDirectory = resolve(values['output-dir'] || fileURLToPath(new URL('../.copilot-tracking/map-loading/', import.meta.url)));
await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

try {
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(target.href, { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'Open map view', exact: true }).click();
    const map = page.locator('.leaflet-container');
    await map.waitFor({ state: 'visible', timeout: 15000 });
    await page.waitForFunction(() => Array.from(document.querySelectorAll('.leaflet-tile-loaded')).some(
      image => image.complete && image.naturalWidth > 0,
    ), { polling: 100, timeout: 30000 });
    const tileUrls = await page.locator('.leaflet-tile-loaded').evaluateAll(images => images.map(image => image.src));
    assert.equal(await page.getByText('Loading map...', { exact: true }).count(), 0);
    const bounds = await map.boundingBox();
    assert.ok(bounds && bounds.width > 200 && bounds.height > 200);
    await page.getByTitle('Zoom In', { exact: true }).click();
    await page.waitForFunction(previous => Array.from(document.querySelectorAll('.leaflet-tile-loaded')).some(
      image => image.complete && image.naturalWidth > 0 && !previous.includes(image.src),
    ), tileUrls, { polling: 100, timeout: 30000 });
    await page.getByTitle(/^Drop Pin: click/).click();
    await map.click({ position: { x: bounds.width * 0.6, y: bounds.height * 0.45 } });
    await page.locator('.free-pin').waitFor({ state: 'visible' });
    await page.screenshot({ path: resolve(outputDirectory, `map-${name}.png`), fullPage: true });
    assert.deepEqual(errors, []);
    results.push({ name, width, height, bounds, decodedTiles: tileUrls.length, zoom: 'passed', pin: 'passed', errors });
    await page.close();
  }
  const report = { scope: 'Public fallback basemap, tiles, zoom, and pins only; AI analysis not invoked.', results };
  await writeFile(resolve(outputDirectory, 'map-results.json'), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}