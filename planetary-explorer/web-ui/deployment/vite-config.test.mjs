import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { loadConfigFromFile } from 'vite';

const projectRoot = fileURLToPath(new URL('../', import.meta.url));
const configPath = fileURLToPath(new URL('../vite.config.ts', import.meta.url));

test('production packaging uses the azd API origin while preserving an explicit override', async () => {
  const originalVite = process.env.VITE_API_BASE_URL;
  const originalAzure = process.env.AZURE_CONTAINER_APP_URL;
  try {
    process.env.VITE_API_BASE_URL = '';
    process.env.AZURE_CONTAINER_APP_URL = 'https://api.example.azurecontainerapps.io';
    const generated = await loadConfigFromFile({ command: 'build', mode: 'production' }, configPath, projectRoot, 'silent');
    assert.equal(generated.config.define['import.meta.env.VITE_API_BASE_URL'], '"https://api.example.azurecontainerapps.io"');

    process.env.VITE_API_BASE_URL = 'https://custom-api.example';
    const explicit = await loadConfigFromFile({ command: 'build', mode: 'production' }, configPath, projectRoot, 'silent');
    assert.equal(explicit.config.define['import.meta.env.VITE_API_BASE_URL'], '"https://custom-api.example"');
  } finally {
    if (originalVite === undefined) delete process.env.VITE_API_BASE_URL;
    else process.env.VITE_API_BASE_URL = originalVite;
    if (originalAzure === undefined) delete process.env.AZURE_CONTAINER_APP_URL;
    else process.env.AZURE_CONTAINER_APP_URL = originalAzure;
  }
});