// REVIEW EVIDENCE — TASK-202a / PR #42 (frontend review of backend branch).
// Spawns the branch's real Python server (`python3 -m server`) on the exact
// contract URL and exercises it through the TASK-206 generated client — the
// same client the overlay/web will ship against. Mirrors mock.test.mjs so any
// behavioral drift between mock and real server is a visible diff.
// Run (from web/): node --import tsx --test mock/review202a.backend.test.mjs
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';

import { renderSmokeCard } from './renderSmoke.mjs';
import { OpenAPI } from '../src/generated/core/OpenAPI.ts';
import { DefaultService } from '../src/generated/services/DefaultService.ts';
import { ApiError } from '../src/generated/core/ApiError.ts';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../..');
const FIXTURES_DIR = path.join(REPO_ROOT, 'contracts/fixtures');

const ajv = new Ajv2020({ strict: false });
const validateVerdict = ajv.compile(
  JSON.parse(readFileSync(path.join(REPO_ROOT, 'contracts/verdict.schema.json'), 'utf8')),
);

const fixtureNames = readdirSync(FIXTURES_DIR)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.slice(0, -'.json'.length));
const readFixture = (name) =>
  JSON.parse(readFileSync(path.join(FIXTURES_DIR, `${name}.json`), 'utf8'));

async function rawPost(route, body) {
  const res = await fetch(`${OpenAPI.BASE}${route}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
}

let serverProc;
before(async () => {
  assert.equal(OpenAPI.BASE, 'http://127.0.0.1:47791/api/v0');
  serverProc = spawn('python3', ['-m', 'server'], {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });
  serverProc.stderr.on('data', (d) => process.stderr.write(`[server] ${d}`));
  // Poll the contract port (server stdout is block-buffered when piped).
  const deadline = Date.now() + 15000;
  for (;;) {
    if (serverProc.exitCode !== null || serverProc.signalCode !== null) {
      throw new Error(`server exited before readiness (code=${serverProc.exitCode})`);
    }
    try {
      await fetch(`${OpenAPI.BASE}/build`, { method: 'GET' });
      break;
    } catch (err) {
      if (Date.now() > deadline) throw new Error(`server start timeout: ${err}`);
      await new Promise((r) => setTimeout(r, 150));
    }
  }

  // Contract: /diff and GET /build are 404 before any build is imported.
  await assert.rejects(DefaultService.getActiveBuild(), (e) => e instanceof ApiError && e.status === 404);
  await assert.rejects(
    DefaultService.diffItem({ item_text: 'Rarity: RARE\nDoomfletch\n' }),
    (e) => e instanceof ApiError && e.status === 404,
  );

  const build = await DefaultService.importBuild({ pob_code: '@skill:Arc;@tag:shock' });
  assert.equal(build.main_skill.name, 'Arc');
});
after(() => new Promise((resolve) => {
  if (!serverProc || serverProc.killed) return resolve();
  serverProc.once('exit', resolve);
  serverProc.kill('SIGTERM');
  setTimeout(resolve, 3000).unref();
}));

test('importBuild -> BuildSummary shape; getActiveBuild round-trips; 422 validation', async () => {
  const build = await DefaultService.getActiveBuild();
  assert.equal(typeof build.build_id, 'string');
  assert.equal(typeof build.character_class, 'string');
  assert.equal(Number.isInteger(build.level), true);
  assert.equal(build.main_skill.name, 'Arc');
  assert.equal(build.main_skill.inferred, true);
  assert.equal(typeof build.main_skill.confidence, 'number');
  assert.ok(['mapping', 'bossing', 'balanced'].includes(build.preset_default));

  // account+character variant per contract oneOf.
  const alt = await DefaultService.importBuild({ account: 'acct', character: 'char' });
  assert.equal(typeof alt.build_id, 'string');

  // both variants at once -> 422; empty body -> 422 (ApiError, contract status).
  await assert.rejects(
    DefaultService.importBuild({ pob_code: 'x', account: 'a', character: 'c' }),
    (e) => e instanceof ApiError && e.status === 422,
  );
  const empty = await rawPost('/build', {});
  assert.equal(empty.status, 422);
  assert.equal(empty.body, null, 'RULING-20: bare error body');

  // restore the Arc build for the diff tests.
  await DefaultService.importBuild({ pob_code: '@skill:Arc;@tag:shock' });
});

test('every contract fixture is reproduced verbatim by the real server and validates against verdict.schema.json', async () => {
  assert.ok(fixtureNames.length >= 7, 'expected TASK-205 fixture set on disk');
  for (const name of fixtureNames) {
    const card = await DefaultService.diffItem({ item_text: `@fixture:${name}` });
    assert.deepEqual(card, readFixture(name), `@fixture:${name} served verbatim`);
    assert.ok(validateVerdict(card), `@fixture:${name}: ${JSON.stringify(validateVerdict.errors)}`);
  }
});

test('all four verdict states reachable via generated client and render on the smoke card (I2)', async () => {
  const byVerdict = new Map();
  for (const name of fixtureNames) byVerdict.set(readFixture(name).verdict, name);
  for (const verdict of ['UPGRADE', 'SIDEGRADE', 'DOWNGRADE', 'CANT_EVALUATE']) {
    assert.ok(byVerdict.has(verdict), `no fixture covers ${verdict}`);
    const card = await DefaultService.diffItem({ item_text: `@fixture:${byVerdict.get(verdict)}` });
    assert.equal(card.verdict, verdict);
    const view = renderSmokeCard(card);
    if (verdict === 'CANT_EVALUATE') {
      assert.equal(view.word, "CAN'T EVALUATE");
      assert.equal(view.offense, '—');
      assert.equal(view.defense, '—');
    } else {
      assert.equal(view.word, verdict);
      assert.match(view.offense, /^[+-]?\d+\.\d%$/);
      assert.match(view.defense, /^[+-]?\d+\.\d%$/);
    }
    assert.equal(view.sentence, card.sentence);
  }
});

test('I3: one-tap override re-diff via generated client — fresh diff_id, values applied, deterministic', async () => {
  const base = await DefaultService.diffItem({ item_text: '@fixture:upgrade_mapping' });
  const flippable = base.assumptions.filter((a) => typeof a.value === 'boolean');
  assert.ok(flippable.length >= 2, 'fixture needs >=2 boolean assumptions');
  const overrides = flippable.slice(0, 2).map((a) => ({ assumption_id: a.id, value: !a.value }));

  const redone = await DefaultService.diffItem({
    item_text: '@fixture:upgrade_mapping',
    preset: base.preset,
    overrides,
  });
  assert.notEqual(redone.diff_id, base.diff_id);
  assert.ok(redone.diff_id.startsWith(`${base.diff_id}#ovr-`), 'override marker in diff_id');
  for (const ov of overrides) {
    assert.equal(redone.assumptions.find((a) => a.id === ov.assumption_id).value, ov.value);
  }
  assert.ok(validateVerdict(redone), JSON.stringify(validateVerdict.errors));

  const again = await DefaultService.diffItem({ item_text: '@fixture:upgrade_mapping', overrides });
  assert.equal(again.diff_id, redone.diff_id, 'identical overrides -> identical diff_id');
});

test('error paths surface as ApiError with contract status; bare bodies (RULING-20)', async () => {
  await assert.rejects(
    DefaultService.diffItem({ item_text: '@error:404' }),
    (e) => e instanceof ApiError && e.status === 404,
  );
  for (const body of [
    { item_text: '@error:422' },
    { item_text: '' },
    { item_text: '   ' },
    { item_text: '@fixture:no_such_fixture' },
    { item_text: 'x', overrides: [{ assumption_id: 'no-value-key' }] },
  ]) {
    await assert.rejects(DefaultService.diffItem(body), (e) => e instanceof ApiError && e.status === 422);
  }
  // contract maxLength 20000 and preset enum enforced server-side.
  const tooLong = await rawPost('/diff', { item_text: 'x'.repeat(20001) });
  assert.equal(tooLong.status, 422);
  assert.equal(tooLong.body, null);
  const badPreset = await rawPost('/diff', { item_text: '@fixture:upgrade_mapping', preset: 'hardcore' });
  assert.equal(badPreset.status, 422);
  assert.equal(badPreset.body, null);
  const malformed = await rawPost('/diff', '{not json');
  assert.equal(malformed.status, 422);
});
