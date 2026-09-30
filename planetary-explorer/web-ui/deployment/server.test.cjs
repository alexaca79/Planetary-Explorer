const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const zlib = require('node:zlib');

const siteRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pe-host-'));
const script = `console.log("${'Planetary Explorer '.repeat(200)}");`;
fs.mkdirSync(path.join(siteRoot, 'assets'));
fs.copyFileSync(path.join(__dirname, 'server.cjs'), path.join(siteRoot, 'server.js'));
fs.copyFileSync(path.join(__dirname, 'package.json'), path.join(siteRoot, 'package.json'));
fs.writeFileSync(path.join(siteRoot, 'index.html'), '<!doctype html><div id="root"></div>');
fs.writeFileSync(path.join(siteRoot, '.env'), 'SECRET=value');
fs.writeFileSync(path.join(siteRoot, 'assets', 'index-AbC123.js'), script);
fs.writeFileSync(path.join(siteRoot, 'assets', 'index-AbC123.js.br'), zlib.brotliCompressSync(script));
fs.writeFileSync(path.join(siteRoot, 'assets', 'index-AbC123.js.gz'), zlib.gzipSync(script));

process.env.PORT = '0';
const server = require(path.join(siteRoot, 'server.js'));

function request(pathname, { method = 'GET', headers = {} } = {}) {
  const { port } = server.address();
  return new Promise((resolve, reject) => {
    const requestHandle = http.request({ host: '127.0.0.1', path: pathname, port, method, headers }, (response) => {
      const chunks = [];
      response.on('data', (chunk) => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }));
    });
    requestHandle.on('error', reject);
    requestHandle.end();
  });
}

test.after(() => new Promise((resolve) => {
  server.close(() => {
    fs.rmSync(siteRoot, { recursive: true, force: true });
    resolve();
  });
}));

test('rejects NUL paths without terminating the server', async () => {
  assert.equal((await request('/%00')).status, 400);
  assert.equal((await request('/')).status, 200);
});

test('serves the shell with browser security headers and revalidation', async () => {
  const response = await request('/');

  assert.equal(response.status, 200);
  assert.equal(response.headers['content-type'], 'text/html; charset=utf-8');
  assert.equal(response.headers['cache-control'], 'no-cache');
  assert.equal(response.headers['x-content-type-options'], 'nosniff');
  assert.equal(response.headers['x-frame-options'], 'DENY');
  assert.match(response.headers['content-security-policy'], /frame-ancestors 'none'/);
  assert.equal(response.headers['referrer-policy'], 'strict-origin-when-cross-origin');
});

test('serves fingerprinted assets precompressed and immutable', async () => {
  const brotli = await request('/assets/index-AbC123.js', { headers: { 'Accept-Encoding': 'gzip, deflate, br' } });
  const gzip = await request('/assets/index-AbC123.js', { headers: { 'Accept-Encoding': 'gzip' } });
  const identity = await request('/assets/index-AbC123.js');

  assert.equal(brotli.headers['content-encoding'], 'br');
  assert.equal(zlib.brotliDecompressSync(brotli.body).toString(), script);
  assert.equal(brotli.headers['cache-control'], 'public, max-age=31536000, immutable');
  assert.equal(brotli.headers.vary, 'Accept-Encoding');
  assert.ok(brotli.body.length < script.length / 10);
  assert.equal(gzip.headers['content-encoding'], 'gzip');
  assert.equal(zlib.gunzipSync(gzip.body).toString(), script);
  assert.equal(identity.headers['content-encoding'], undefined);
  assert.equal(identity.body.toString(), script);
});

test('answers conditional requests with 304', async () => {
  const first = await request('/assets/index-AbC123.js', { headers: { 'Accept-Encoding': 'br' } });
  const second = await request('/assets/index-AbC123.js', {
    headers: { 'Accept-Encoding': 'br', 'If-None-Match': first.headers.etag },
  });

  assert.equal(second.status, 304);
  assert.equal(second.body.length, 0);
});

test('never serves host files or dotfiles', async () => {
  for (const pathname of ['/server.js', '/package.json', '/.env']) {
    const response = await request(pathname);
    assert.equal(response.status, 404, pathname);
    assert.doesNotMatch(response.body.toString(), /SECRET|createServer|planetary-explorer-ui-deployment/);
  }
});

test('returns 404 for missing fingerprinted assets instead of the app shell', async () => {
  const response = await request('/assets/index-Old999.js');

  assert.equal(response.status, 404);
  assert.equal(response.headers['cache-control'], 'no-store');
});

test('falls back to the app shell for client-side routes', async () => {
  const response = await request('/history/session-1');

  assert.equal(response.status, 200);
  assert.match(response.body.toString(), /id="root"/);
});

test('rejects methods other than GET and HEAD', async () => {
  const post = await request('/', { method: 'POST' });
  const head = await request('/', { method: 'HEAD' });

  assert.equal(post.status, 405);
  assert.equal(post.headers.allow, 'GET, HEAD');
  assert.equal(head.status, 200);
  assert.equal(head.body.length, 0);
});