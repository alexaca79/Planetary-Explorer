import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { chromium } from '../planetary-explorer/web-ui/node_modules/playwright/index.mjs';
import { authenticateHistoryBrowser, deleteHistoryFixture, historyApiHeaders } from './browser_history_auth.mjs';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const { values } = parseArgs({
  options: {
    'base-url': { type: 'string', default: 'http://127.0.0.1:5187' },
    'api-url': { type: 'string', default: 'http://127.0.0.1:8026' },
    'output-dir': { type: 'string', default: '.copilot-tracking/chat-memory-validation/browser' },
    help: { type: 'boolean', default: false },
    'allow-production': { type: 'boolean', default: false },
    'release-args': { type: 'string' },
  },
});
if (values.help) {
  console.log('Usage: node scripts/verify_chat_memory.mjs --base-url URL --api-url URL [--output-dir PATH]');
  console.log('Requires an isolated local backend with temporary history. Creates and deletes fixture chats; makes no model calls.');
  process.exit(0);
}
const isProduction = [values['base-url'], values['api-url']].some(origin => !['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
let releaseArgs;
if (isProduction) {
  assert.ok(values['allow-production'] && values['release-args'], 'Production checks require explicit consent and release binding.');
  releaseArgs = JSON.parse(readFileSync(values['release-args'], 'utf8').replace(/^\uFEFF/, ''));
  assert.equal(new URL(releaseArgs[releaseArgs.indexOf('--base-url') + 1]).origin, new URL(values['api-url']).origin);
  assert.equal(new URL(releaseArgs[releaseArgs.indexOf('--frontend-url') + 1]).origin, new URL(values['base-url']).origin);
  execFileSync(process.env.PYTHON || 'python', [new URL('./verify_get_started_scenarios.py', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), ...releaseArgs, '--verify-release-only'], { stdio: 'pipe' });
}
const apiHeaders = isProduction ? historyApiHeaders() : {};
const outputDirectory = resolve(values['output-dir']);
await mkdir(outputDirectory, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
const fixtureIds = [];
const cleanup = [];
let failure;
const endpoint = sessionId => `${values['api-url']}/api/chat-history/sessions/${sessionId}`;

async function saveFixture(sessionId, title, messages) {
  fixtureIds.push(sessionId);
  const response = await fetch(endpoint(sessionId), {
    method: 'PUT',
    headers: { ...apiHeaders, 'Content-Type': 'application/json' },
    body: JSON.stringify({ expectedRevision: 0, mutationId: `${sessionId}-save`, title, messages, memoryEnabled: true }),
  });
  assert.equal(response.status, 200, `Fixture save failed: ${response.status}`);
}

try {
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844], ['small-mobile', 320, 568]]) {
    const suffix = `${Date.now()}-${name}`;
    const sourceId = `memory-source-${suffix}`;
    const currentId = `memory-current-${suffix}`;
    const sourceTitle = `Thunder Bay baseline ${suffix}`;
    const currentTitle = `Long conversation memory ${suffix}`;
    await saveFixture(sourceId, sourceTitle, [{ role: 'user', content: 'Our Thunder Bay baseline is June 1, 2026.' }]);
    await saveFixture(currentId, currentTitle, [
      { role: 'user', content: 'Which baseline did we choose earlier?' },
      {
        role: 'assistant', content: 'Fixture transcript: the selected baseline was June 1, 2026.',
        memory: {
          enabled: true, provider: 'history', earlierTurns: 2,
          sources: [{ sessionId: sourceId, title: sourceTitle, turn: 0, updatedAt: new Date().toISOString() }],
        },
      },
    ]);
    const page = await browser.newPage({ viewport: { width, height } });
    if (isProduction) await authenticateHistoryBrowser(page.context(), values['base-url']);
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    try {
      await page.goto(values['base-url'], { waitUntil: 'networkidle' });
      await page.getByRole('button', { name: 'Open map view', exact: true }).click();
      const memorySwitch = page.getByRole('switch', { name: 'Use chat memory' });
      await memorySwitch.waitFor({ state: 'visible' });
      await page.getByRole('button', { name: 'Open saved chat sessions' }).click();
      const drawer = page.getByRole('complementary', { name: 'Saved chat sessions' });
      const filter = drawer.getByRole('searchbox', { name: 'Search saved sessions' });
      await filter.fill(sourceTitle);
      const [excludedSave] = await Promise.all([
        page.waitForResponse(response => response.url() === endpoint(sourceId) && response.request().method() === 'PUT'),
        drawer.getByRole('checkbox', { name: `Include ${sourceTitle} in memory` }).uncheck(),
      ]);
      assert.equal(excludedSave.status(), 200);
      assert.equal((await (await fetch(endpoint(sourceId), { headers: apiHeaders })).json()).memoryEnabled, false);
      await filter.fill(currentTitle);
      await drawer.getByRole('button', { name: `Open ${currentTitle}`, exact: true }).click();
      await drawer.waitFor({ state: 'hidden' });
      assert.equal(await memorySwitch.isChecked(), true);
      await page.mouse.move(2, height - 2);
      await page.getByText('Recalled context', { exact: true }).click();
      await page.getByText('Earlier in this chat: 2 entries', { exact: true }).waitFor({ state: 'visible' });
      const [memorySave] = await Promise.all([
        page.waitForResponse(response => (
          response.url() === endpoint(currentId)
          && response.request().method() === 'PUT'
          && response.request().postDataJSON().memoryEnabled === false
        )),
        memorySwitch.uncheck(),
      ]);
      assert.equal(memorySave.status(), 200);
      assert.equal((await (await fetch(endpoint(currentId), { headers: apiHeaders })).json()).memoryEnabled, false);
      await page.getByRole('button', { name: 'Open saved chat sessions' }).click();
      await drawer.waitFor({ state: 'visible' });
      await filter.fill(currentTitle);
      const bounds = await drawer.boundingBox();
      assert.ok(bounds && bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= width + 1 && bounds.y + bounds.height <= height + 1, `Drawer outside ${name} viewport: ${JSON.stringify(bounds)}`);
      const overflow = await drawer.evaluate(element => element.scrollWidth > element.clientWidth);
      assert.equal(overflow, false, `History overflow at ${width}px`);
      await page.screenshot({ path: resolve(outputDirectory, `memory-${name}.png`), fullPage: true });
      page.once('dialog', dialog => dialog.accept());
      const deletion = page.waitForResponse(response => response.url() === endpoint(currentId) && response.request().method() === 'DELETE');
      await drawer.getByRole('button', { name: `Delete ${currentTitle}`, exact: true }).click();
      assert.equal((await deletion).status(), 204);
      assert.equal((await fetch(endpoint(currentId), { headers: apiHeaders })).status, 404);
      assert.deepEqual(errors, []);
      results.push({ name, width, height, exclusion: 'passed', restore: 'passed', memorySetting: 'passed', sourceMetadata: 'passed', deletion: 'passed', overflow });
    } catch (error) {
      await page.screenshot({ path: resolve(outputDirectory, `failed-${name}.png`), fullPage: true });
      throw error;
    } finally {
      await page.close();
      await deleteHistoryFixture(endpoint(sourceId), apiHeaders);
    }
  }
  if (isProduction) execFileSync(process.env.PYTHON || 'python', [new URL('./verify_get_started_scenarios.py', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), ...releaseArgs, '--verify-release-only'], { stdio: 'pipe' });
} catch (error) {
  failure = error;
} finally {
  for (const sessionId of fixtureIds) {
    try {
      const status = await deleteHistoryFixture(endpoint(sessionId), apiHeaders);
      cleanup.push({ sessionId, status });
    } catch (error) {
      cleanup.push({ sessionId, error: error.message });
      failure ??= error;
    }
  }
  await browser.close();
}
const report = {
  scope: isProduction ? 'Deployed authenticated history and memory controls with real EasyAuth login; fixture transcripts, no model calls.' : 'Local fixture history and memory controls; no live model or Search inference.',
  status: failure ? 'failed' : 'passed', results, cleanup,
};
await writeFile(resolve(outputDirectory, 'results.json'), `${JSON.stringify(report, null, 2)}\n`);
if (failure) throw failure;
console.log(JSON.stringify(report));