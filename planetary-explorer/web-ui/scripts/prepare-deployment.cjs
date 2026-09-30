const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const projectRoot = path.resolve(__dirname, '..');
const deploymentRoot = path.join(projectRoot, 'deployment');
const outputRoot = path.join(projectRoot, 'dist');
const compressibleExtensions = new Set(['.css', '.html', '.js', '.json', '.map', '.svg', '.txt', '.webmanifest']);
const minimumCompressedBytes = 1024;

function listFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory() ? listFiles(entryPath) : [entryPath];
  });
}

// Precompress text assets so the host sends Brotli or gzip without
// spending CPU per request.
function precompress(directory) {
  let written = 0;
  for (const filePath of listFiles(directory)) {
    if (!compressibleExtensions.has(path.extname(filePath).toLowerCase())) continue;
    const body = fs.readFileSync(filePath);
    if (body.length < minimumCompressedBytes) continue;
    const brotli = zlib.brotliCompressSync(body, {
      params: {
        [zlib.constants.BROTLI_PARAM_QUALITY]: zlib.constants.BROTLI_MAX_QUALITY,
        [zlib.constants.BROTLI_PARAM_SIZE_HINT]: body.length,
      },
    });
    const gzip = zlib.gzipSync(body, { level: zlib.constants.Z_BEST_COMPRESSION });
    if (brotli.length < body.length) {
      fs.writeFileSync(`${filePath}.br`, brotli);
      written += 1;
    }
    if (gzip.length < body.length) {
      fs.writeFileSync(`${filePath}.gz`, gzip);
      written += 1;
    }
  }
  return written;
}

const compressedFiles = precompress(outputRoot);

fs.copyFileSync(
  path.join(deploymentRoot, 'server.cjs'),
  path.join(outputRoot, 'server.js'),
);
fs.copyFileSync(
  path.join(deploymentRoot, 'package.json'),
  path.join(outputRoot, 'package.json'),
);

console.log(`Prepared dependency-free App Service host with ${compressedFiles} precompressed assets.`);