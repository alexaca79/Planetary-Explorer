import assert from 'node:assert/strict';
import test from 'node:test';
import { deleteHistoryFixture } from '../browser_history_auth.mjs';

for (const status of [204, 404]) {
  test(`accepts completed history cleanup with HTTP ${status}`, async () => {
    const headers = { Authorization: 'Bearer fixture-token' };
    const request = async (url, options) => {
      assert.equal(url, 'https://api.example/api/chat-history/sessions/fixture');
      assert.equal(options.method, 'DELETE');
      assert.equal(options.redirect, 'error');
      assert.equal(options.headers, headers);
      return { status };
    };

    assert.equal(await deleteHistoryFixture('https://api.example/api/chat-history/sessions/fixture', headers, request), status);
  });
}

for (const status of [401, 403, 429, 503]) {
  test(`rejects failed history cleanup with HTTP ${status}`, async () => {
    await assert.rejects(
      deleteHistoryFixture('https://api.example/fixture', {}, async () => ({ status })),
      new RegExp(`History fixture cleanup failed: HTTP ${status}`),
    );
  });
}

test('rejects history cleanup transport failures', async () => {
  await assert.rejects(
    deleteHistoryFixture('https://api.example/fixture', {}, async () => { throw new Error('network unavailable'); }),
    /network unavailable/,
  );
});