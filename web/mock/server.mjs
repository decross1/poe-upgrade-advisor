#!/usr/bin/env node
// TASK-206 fixture mock for POST /diff — lets the FE exercise the real HTTP
// contract (generated client, real port, real error codes) before server/
// exists. DELETED when TASK-202 lands (its DoD includes removing this server).
//
// Zero runtime dependencies. Fixtures are read from contracts/fixtures/ on
// every server start — never inlined. Routing rules are documented in
// web/README.md ("Fixture mock server"); keep that section in sync.
import http from 'node:http';
import { readdirSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// Exact server URL from contracts/openapi.yaml (`servers[0].url`):
//   http://127.0.0.1:47791/api/v0
// A test in mock.test.mjs asserts these constants against the contract text.
export const CONTRACT_HOST = '127.0.0.1';
export const CONTRACT_PORT = 47791;
export const CONTRACT_BASE_PATH = '/api/v0';
export const DEFAULT_FIXTURES_DIR = path.resolve(HERE, '../../contracts/fixtures');

const DEFAULT_FIXTURE = 'upgrade_mapping';
const VALID_PRESETS = ['mapping', 'bossing', 'balanced'];

/** Load every *.json fixture from dir, keyed by basename without extension. */
export function loadFixtures(dir = DEFAULT_FIXTURES_DIR) {
  const fixtures = new Map();
  for (const file of readdirSync(dir).sort()) {
    if (file.endsWith('.json')) {
      fixtures.set(file.slice(0, -'.json'.length), JSON.parse(readFileSync(path.join(dir, file), 'utf8')));
    }
  }
  return fixtures;
}

function overridesSuffix(overrides) {
  const hash = createHash('sha256').update(JSON.stringify(overrides)).digest('hex').slice(0, 12);
  return `#ovr-${hash}`;
}

/**
 * Pure routing decision — see web/README.md for the documented rules.
 * @returns {{status: number, card?: object}}
 */
export function route(body, fixtures) {
  if (typeof body !== 'object' || body === null
      || typeof body.item_text !== 'string' || body.item_text.trim() === '') {
    return { status: 422 }; // unparseable item text
  }
  const text = body.item_text;
  if (text.includes('@error:404')) return { status: 404 }; // no active build
  if (text.includes('@error:422')) return { status: 422 }; // unparseable item text

  let name = DEFAULT_FIXTURE;
  const marker = text.match(/@fixture:([A-Za-z0-9_-]+)/);
  if (marker) {
    if (!fixtures.has(marker[1])) return { status: 422 };
    name = marker[1];
  }

  const pristine = fixtures.get(name);
  const card = structuredClone(pristine);

  // Echo a valid request preset, mirroring the stateless re-diff flow
  // (docs/specs/verdict_card.md §7: FE echoes the last response's preset).
  if (VALID_PRESETS.includes(body.preset)) card.preset = body.preset;

  // I3 / RULING-16/17 override round-trip: apply every override to the
  // matching assumption (by Assumption.id, never source_rule) and mint a new
  // deterministic diff_id, proving the response is a fresh diff.
  if (Array.isArray(body.overrides) && body.overrides.length > 0) {
    for (const ov of body.overrides) {
      if (typeof ov !== 'object' || ov === null
          || typeof ov.assumption_id !== 'string' || !('value' in ov)) continue;
      const target = card.assumptions.find((a) => a.id === ov.assumption_id);
      if (target) target.value = ov.value;
    }
    card.diff_id = `${pristine.diff_id}${overridesSuffix(body.overrides)}`;
  }

  return { status: 200, card };
}

export function createMockServer({ fixturesDir = DEFAULT_FIXTURES_DIR } = {}) {
  const fixtures = loadFixtures(fixturesDir);
  return http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    if (req.method !== 'POST' || pathname !== `${CONTRACT_BASE_PATH}/diff`) {
      res.writeHead(404).end(); // mock implements only POST /diff
      return;
    }
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 1_000_000) req.destroy(); // far above the contract's 20000-char item_text cap
    });
    req.on('end', () => {
      let body;
      try {
        body = JSON.parse(raw);
      } catch {
        res.writeHead(422).end();
        return;
      }
      const { status, card } = route(body, fixtures);
      if (status === 200) {
        res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(card));
      } else {
        // RULING-20: error states are status-code only (bare body).
        res.writeHead(status).end();
      }
    });
  });
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  const host = process.env.MOCK_HOST ?? CONTRACT_HOST;
  const port = Number(process.env.MOCK_PORT ?? CONTRACT_PORT);
  const server = createMockServer();
  server.listen(port, host, () => {
    console.log(`mock POST ${CONTRACT_BASE_PATH}/diff on http://${host}:${port} (${loadFixtures().size} fixtures loaded)`);
  });
}
