// TASK-206 acceptance tests. Single file on purpose: every test shares one
// server bound to the real contract port (127.0.0.1:47791), which no two
// parallel test processes may hold at once. Run: npm test (from web/).
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';

import {
  CONTRACT_BASE_PATH,
  CONTRACT_HOST,
  CONTRACT_PORT,
  DEFAULT_FIXTURES_DIR,
  createMockServer,
} from './server.mjs';
import { renderSmokeCard } from './renderSmoke.mjs';
// Generated client (TS) — loaded via tsx; see web/package.json test script.
import { OpenAPI } from '../src/generated/core/OpenAPI.ts';
import { DefaultService } from '../src/generated/services/DefaultService.ts';
import { ApiError } from '../src/generated/core/ApiError.ts';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../..');
const BASE_URL = `http://${CONTRACT_HOST}:${CONTRACT_PORT}${CONTRACT_BASE_PATH}`;

const ajv = new Ajv2020({ strict: false });
const validateVerdict = ajv.compile(
  JSON.parse(readFileSync(path.join(REPO_ROOT, 'contracts/verdict.schema.json'), 'utf8')),
);

const fixtureNames = readdirSync(DEFAULT_FIXTURES_DIR)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.slice(0, -'.json'.length));

function readFixture(name) {
  return JSON.parse(readFileSync(path.join(DEFAULT_FIXTURES_DIR, `${name}.json`), 'utf8'));
}

async function postDiff(body) {
  const res = await fetch(`${BASE_URL}/diff`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
}

let server;
before(async () => {
  server = createMockServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(CONTRACT_PORT, CONTRACT_HOST, resolve);
  });
});
after(() => new Promise((resolve) => server.close(resolve)));

test('mock bind address matches the exact server URL in contracts/openapi.yaml', () => {
  const spec = readFileSync(path.join(REPO_ROOT, 'contracts/openapi.yaml'), 'utf8');
  assert.match(spec, /url:\s*http:\/\/127\.0\.0\.1:47791\/api\/v0/);
  assert.equal(`${CONTRACT_HOST}:${CONTRACT_PORT}${CONTRACT_BASE_PATH}`, '127.0.0.1:47791/api/v0');
  // The generated client defaults to the same URL (servers[0] from the spec).
  assert.equal(OpenAPI.BASE, 'http://127.0.0.1:47791/api/v0');
});

test('every fixture in contracts/fixtures is served from disk and validates against verdict.schema.json', async () => {
  assert.ok(fixtureNames.length >= 7, 'expected TASK-205 fixture set on disk');
  for (const name of fixtureNames) {
    const { status, body } = await postDiff({ item_text: `@fixture:${name}` });
    assert.equal(status, 200, `@fixture:${name}`);
    assert.deepEqual(body, readFixture(name), `@fixture:${name} must be served verbatim from disk`);
    assert.ok(validateVerdict(body), `@fixture:${name}: ${JSON.stringify(validateVerdict.errors)}`);
  }
});

test('deterministic selection reaches each of the four verdict states', async () => {
  const byVerdict = new Map();
  for (const name of fixtureNames) byVerdict.set(readFixture(name).verdict, name);
  for (const verdict of ['UPGRADE', 'SIDEGRADE', 'DOWNGRADE', 'CANT_EVALUATE']) {
    assert.ok(byVerdict.has(verdict), `no fixture covers ${verdict}`);
    const { status, body } = await postDiff({ item_text: `rarity: rare\n@fixture:${byVerdict.get(verdict)}` });
    assert.equal(status, 200);
    assert.equal(body.verdict, verdict);
  }
});

test('no marker selects the documented default fixture', async () => {
  const { status, body } = await postDiff({ item_text: 'Rarity: RARE\nDoomfletch\n' });
  assert.equal(status, 200);
  assert.deepEqual(body, readFixture('upgrade_mapping'));
});

test('error paths: @error:404 -> 404, @error:422 -> 422, unparseable requests -> 422 (status-code only)', async () => {
  for (const body of [{ item_text: '@error:404' }]) {
    const res = await postDiff(body);
    assert.equal(res.status, 404);
    assert.equal(res.body, null, 'RULING-20: bare error body');
  }
  for (const body of [
    { item_text: '@error:422' },
    { item_text: '' },
    { item_text: '   ' },
    {},
    { item_text: '@fixture:no_such_fixture' },
  ]) {
    const res = await postDiff(body);
    assert.equal(res.status, 422, JSON.stringify(body));
    assert.equal(res.body, null, 'RULING-20: bare error body');
  }
  const malformed = await postDiff('{not json');
  assert.equal(malformed.status, 422);
});

test('overrides round-trip (I3, RULING-16/17): new diff_id, values applied, schema-valid', async () => {
  const base = readFixture('upgrade_mapping');
  const flippable = base.assumptions.filter((a) => typeof a.value === 'boolean');
  assert.ok(flippable.length >= 2, 'fixture needs >=2 boolean assumptions for accumulation check');

  const overrides = flippable.slice(0, 2).map((a) => ({ assumption_id: a.id, value: !a.value }));
  const { status, body } = await postDiff({
    item_text: '@fixture:upgrade_mapping',
    preset: base.preset,
    overrides,
  });
  assert.equal(status, 200);
  assert.notEqual(body.diff_id, base.diff_id, 'override response must be a fresh diff');
  assert.ok(body.diff_id.startsWith(`${base.diff_id}#ovr-`), 'diff_id carries an override marker');
  // RULING-17: the full accumulated override set is applied, by Assumption.id.
  for (const ov of overrides) {
    assert.equal(body.assumptions.find((a) => a.id === ov.assumption_id).value, ov.value);
  }
  assert.ok(validateVerdict(body), JSON.stringify(validateVerdict.errors));

  // Deterministic: identical overrides -> identical diff_id.
  const again = await postDiff({ item_text: '@fixture:upgrade_mapping', overrides });
  assert.equal(again.body.diff_id, body.diff_id);
});

test('generated client round-trips against the mock and the card renders (all four states)', async () => {
  const seen = new Map();
  for (const name of fixtureNames) seen.set(readFixture(name).verdict, name);
  for (const [verdict, name] of seen) {
    const card = await DefaultService.diffItem({ item_text: `@fixture:${name}` });
    assert.equal(card.verdict, verdict);
    assert.ok(validateVerdict(card), JSON.stringify(validateVerdict.errors));
    const view = renderSmokeCard(card);
    if (verdict === 'CANT_EVALUATE') {
      assert.equal(view.word, "CAN'T EVALUATE");
      assert.equal(view.offense, '—');
      assert.equal(view.defense, '—');
    } else {
      assert.equal(view.word, verdict);
      assert.match(view.offense, /^[+-]?\d+\.\d%$/);
    }
    assert.equal(view.sentence, card.sentence);
  }
});

test('generated client surfaces 404/422 as ApiError with the contract status', async () => {
  await assert.rejects(
    DefaultService.diffItem({ item_text: '@error:404' }),
    (err) => err instanceof ApiError && err.status === 404,
  );
  await assert.rejects(
    DefaultService.diffItem({ item_text: '@error:422' }),
    (err) => err instanceof ApiError && err.status === 422,
  );
});

test('generated client re-diff sends accumulated overrides (RULING-16/17 shape)', async () => {
  const base = await DefaultService.diffItem({ item_text: '@fixture:upgrade_mapping' });
  const chip = base.assumptions.find((a) => typeof a.value === 'boolean');
  const redone = await DefaultService.diffItem({
    item_text: '@fixture:upgrade_mapping',
    preset: base.preset,
    overrides: [{ assumption_id: chip.id, value: !chip.value }],
  });
  assert.notEqual(redone.diff_id, base.diff_id);
  assert.equal(redone.assumptions.find((a) => a.id === chip.id).value, !chip.value);
});
