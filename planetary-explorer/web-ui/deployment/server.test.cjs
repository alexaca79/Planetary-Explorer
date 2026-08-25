const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');

process.env.PORT = '0';
const server = require('./server.cjs');

function request(pathname) {
  const { port } = server.address();
  return new Promise((resolve, reject) => {
    const requestHandle = http.get(
      { host: '127.0.0.1', path: pathname, port },
      (response) => {
        response.resume();
        response.on('end', () => resolve(response.statusCode));
      },
    );
    requestHandle.on('error', reject);
  });
}

test.after(() => new Promise((resolve) => server.close(resolve)));

test('rejects NUL paths without terminating the server', async () => {
  assert.equal(await request('/%00'), 400);
  assert.equal(await request('/server.cjs'), 200);
});