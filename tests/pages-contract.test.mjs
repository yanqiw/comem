import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const root = new URL('../', import.meta.url);
const text = (file) => readFile(new URL(file, root), 'utf8');

test('VitePress publishes project documentation below /comem/', async () => {
  const config = await text('docs/.vitepress/config.mts');
  const home = await text('docs/index.md');
  const pyproject = await text('pyproject.toml');

  assert.match(config, /base:\s*['"]\/comem\/['"]/);
  assert.match(config, /Coordination Memory/);
  assert.match(config, /https:\/\/github\.com\/yanqiw\/comem/);
  assert.match(config, /\/quickstart/);
  assert.match(home, /layout:\s*home/);
  assert.match(home, /Acceptance is a decision/);
  assert.match(pyproject, /Homepage = "https:\/\/yanqiw\.github\.io\/comem\/"/);
});

test('Pages workflow builds and deploys the VitePress artifact', async () => {
  const workflow = await text('.github/workflows/pages.yml');
  assert.match(workflow, /pages:\s*write/);
  assert.match(workflow, /id-token:\s*write/);
  assert.match(workflow, /npm ci/);
  assert.match(workflow, /npm run docs:build/);
  assert.match(workflow, /actions\/upload-pages-artifact@v3/);
  assert.match(workflow, /actions\/deploy-pages@v4/);
  assert.match(workflow, /cancel-in-progress:\s*true/);
});
