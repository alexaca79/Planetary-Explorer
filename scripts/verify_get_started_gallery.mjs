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
  console.log('Usage: node scripts/verify_get_started_gallery.mjs [--base-url URL] [--output-dir PATH]');
  console.log('Checks local gallery layout and keyboard behavior only; does not submit analyses.');
  process.exit(0);
}

const target = new URL(values['base-url']);
if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname)) {
  throw new Error('Gallery verification requires a loopback URL. Use the release-bound image verifier for production.');
}
const outputDirectory = resolve(values['output-dir'] || fileURLToPath(new URL('../.copilot-tracking/gallery/', import.meta.url)));
await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];

try {
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844], ['small-mobile', 320, 568]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(target.href, { waitUntil: 'networkidle' });
    const trigger = page.getByRole('button', { name: 'Get Started', exact: true });
    await trigger.focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Get Started' });
    await dialog.waitFor({ state: 'visible' });
    const close = dialog.getByRole('button', { name: 'Close', exact: true });
    assert.equal(await close.evaluate(element => element === document.activeElement), true);
    if (width < 768) {
      const moduleHeights = await dialog.locator('.module-selector-btn').evaluateAll(
        elements => elements.map(element => element.getBoundingClientRect().height),
      );
      assert.ok(moduleHeights.every(value => value <= 100), `Oversized mobile module controls: ${moduleHeights}`);
    }
    await page.keyboard.press('Shift+Tab');
    assert.equal(await dialog.evaluate(element => element.contains(document.activeElement)), true);
    await page.keyboard.press('Tab');
    assert.equal(await close.evaluate(element => element === document.activeElement), true);
    await dialog.getByRole('button', { name: /^Vision/ }).click();
    await dialog.getByText(
      'Show Sentinel-2 imagery over Toronto, Canada from 2026-06-01 to 2026-08-26',
      { exact: true },
    ).waitFor();
    const bounds = await dialog.boundingBox();
    assert.ok(bounds && bounds.x >= 0 && bounds.y >= 0
      && bounds.x + bounds.width <= width && bounds.y + bounds.height <= height);
    const overflow = await dialog.evaluate(element => element.scrollWidth > element.clientWidth);
    assert.equal(overflow, false);
    await page.screenshot({ path: resolve(outputDirectory, `get-started-${name}.png`), fullPage: true });
    await page.keyboard.press('Escape');
    assert.equal(await dialog.count(), 0);
    assert.equal(await trigger.evaluate(element => element === document.activeElement), true);
    assert.deepEqual(errors, []);
    results.push({ name, width, height, bounds, overflow, errors, keyboard: 'passed' });
    await page.close();
  }
  const report = {
    scope: 'Gallery layout and keyboard behavior only; map pixels and AI analysis are unverified.',
    results,
  };
  await writeFile(resolve(outputDirectory, 'browser-results.json'), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}