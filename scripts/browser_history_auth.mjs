import assert from 'node:assert/strict';

export async function authenticateHistoryBrowser(context, appUrl) {
  const token = process.env.PLANETARY_EXPLORER_ACCESS_TOKEN;
  assert.ok(token, 'An application-scoped user token is required for history browser verification.');
  const origin = new URL(appUrl).origin;
  assert.equal(new URL(origin).protocol, 'https:', 'History sign-in requires HTTPS.');
  const login = await context.request.post(`${origin}/.auth/login/aad`, {
    data: { access_token: token },
    maxRedirects: 0,
    timeout: 30000,
  });
  assert.equal(login.status(), 200, 'EasyAuth rejected the signed-in user token.');
  const session = await login.json();
  assert.ok(session.authenticationToken, 'EasyAuth did not issue a session token.');
  const identity = await context.request.get(`${origin}/.auth/me`, {
    headers: { 'X-ZUMO-AUTH': session.authenticationToken }, maxRedirects: 0,
  });
  assert.equal(identity.status(), 200, 'EasyAuth session lookup failed.');
  const profiles = await identity.json();
  assert.ok(Array.isArray(profiles) && profiles.length > 0, 'EasyAuth did not establish a browser identity.');
  assert.ok(profiles[0].id_token || profiles[0].access_token, 'EasyAuth did not expose a token for API forwarding.');
  await context.route(`${origin}/.auth/**`, async route => {
    await route.continue({ headers: { ...route.request().headers(), 'X-ZUMO-AUTH': session.authenticationToken } });
  });
}

export function historyApiHeaders() {
  const token = process.env.PLANETARY_EXPLORER_ACCESS_TOKEN;
  assert.ok(token, 'An application-scoped user token is required.');
  return { Authorization: `Bearer ${token}` };
}

export async function deleteHistoryFixture(url, headers, request = fetch) {
  const response = await request(url, {
    method: 'DELETE', headers, redirect: 'error', signal: AbortSignal.timeout(30000),
  });
  assert.ok([204, 404].includes(response.status), `History fixture cleanup failed: HTTP ${response.status}`);
  return response.status;
}