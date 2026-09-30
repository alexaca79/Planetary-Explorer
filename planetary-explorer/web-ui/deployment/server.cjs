const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const path = require('path');

const port = process.env.PORT || 8080;
const root = __dirname;
const contentTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};
// Host files deployed beside the bundle; never serve them as site content.
const hiddenFiles = new Set(['/package.json', '/server.cjs', '/server.js']);
const encodings = [
  ['br', '.br'],
  ['gzip', '.gz'],
];
const securityHeaders = {
  'Content-Security-Policy': "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'",
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(self)',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY',
};
const fileCache = new Map();

function loadFile(filePath) {
  let entry = fileCache.get(filePath);
  if (!entry) {
    const body = fs.readFileSync(filePath);
    const digest = crypto.createHash('sha256').update(body).digest('base64url').slice(0, 27);
    entry = { body, etag: `"${digest}"` };
    fileCache.set(filePath, entry);
  }
  return entry;
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

function cacheControl(pathname) {
  // Vite fingerprints everything under /assets/, so those URLs never change.
  return pathname.startsWith('/assets/') ? 'public, max-age=31536000, immutable' : 'no-cache';
}

function send(request, response, status, headers, body) {
  response.writeHead(status, { ...securityHeaders, ...headers });
  response.end(request.method === 'HEAD' ? undefined : body);
}

function sendFile(request, response, filePath, pathname) {
  const accepted = String(request.headers['accept-encoding'] || '');
  const extension = path.extname(filePath).toLowerCase();
  const headers = {
    'Cache-Control': cacheControl(pathname),
    'Content-Type': contentTypes[extension] || 'application/octet-stream',
    Vary: 'Accept-Encoding',
  };
  let source = filePath;
  for (const [encoding, suffix] of encodings) {
    if (new RegExp(`\\b${encoding}\\b`).test(accepted) && isFile(`${filePath}${suffix}`)) {
      source = `${filePath}${suffix}`;
      headers['Content-Encoding'] = encoding;
      break;
    }
  }
  let entry;
  try {
    entry = loadFile(source);
  } catch {
    send(request, response, 500, { 'Cache-Control': 'no-store' }, 'Internal server error');
    return;
  }
  headers.ETag = entry.etag;
  if (request.headers['if-none-match'] === entry.etag) {
    send(request, response, 304, headers);
    return;
  }
  headers['Content-Length'] = entry.body.length;
  send(request, response, 200, headers, entry.body);
}

const server = http.createServer((request, response) => {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    send(request, response, 405, { Allow: 'GET, HEAD', 'Cache-Control': 'no-store' }, 'Method not allowed');
    return;
  }
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    if (pathname.includes('\0')) {
      throw new URIError('NUL byte in URL path');
    }
  } catch {
    send(request, response, 400, { 'Cache-Control': 'no-store' }, 'Bad request');
    return;
  }
  const requestedPath = path.resolve(root, `.${pathname}`);
  if (requestedPath !== root && !requestedPath.startsWith(`${root}${path.sep}`)) {
    send(request, response, 403, { 'Cache-Control': 'no-store' }, 'Forbidden');
    return;
  }
  const hidden = hiddenFiles.has(pathname) || pathname.split('/').some((part) => part.startsWith('.'));
  if (!hidden && isFile(requestedPath)) {
    sendFile(request, response, requestedPath, pathname);
    return;
  }
  if (hidden || pathname.startsWith('/assets/')) {
    // A missing fingerprinted asset must not receive index.html, which would
    // be cached under a script URL and break the page.
    send(request, response, 404, { 'Cache-Control': 'no-store' }, 'Not found');
    return;
  }
  sendFile(request, response, path.join(root, 'index.html'), '/index.html');
});

server.listen(port, () => {
  console.log(`Server running on port ${port}`);
});

module.exports = server;