#!/usr/bin/env node
// TASK-206 fixture mock for POST /diff (+ TASK-207: GET/POST /build) — lets
// the FE exercise the real HTTP contract (generated client, real port, real
// error codes) before server/ exists. DELETED when TASK-202 lands (its DoD
// includes removing this server).
//
// Zero runtime dependencies. Fixtures are read from contracts/fixtures/ (and
// web/mock/fixtures/ for FE-local ones) on every server start — never
// inlined. Routing rules are documented in web/README.md ("Fixture mock
// server"); keep that section in sync.
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

// TASK-207: the build-summary fixture is FE-local because contracts/ is a
// protected path and issue #29 carries no protected-change label — see
// web/mock/fixtures/README.md for the promotion path.
export const BUILD_FIXTURE_PATH = path.resolve(HERE, 'fixtures/build_summary.json');

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

/** Load the FE-local BuildSummary fixture from disk (never inlined). */
export function loadBuildSummary(file = BUILD_FIXTURE_PATH) {
  return JSON.parse(readFileSync(file, 'utf8'));
}

/**
 * TASK-207 — pure routing decision for POST /build. Accepts exactly the
 * contract's oneOf request shape (a non-empty `pob_code`, or a non-empty
 * `account` + `character` pair); anything else is the 422 path. The marker
 * `@error:422` inside pob_code forces the invalid-code path, mirroring the
 * /diff marker table. On success the FE-local fixture is returned verbatim.
 * @returns {{status: number, summary?: object}}
 */
export function routeBuild(body, summary) {
  if (typeof body !== 'object' || body === null) return { status: 422 };
  const hasCode = typeof body.pob_code === 'string' && body.pob_code.trim() !== '';
  const hasAccount =
    typeof body.account === 'string' && body.account.trim() !== '' &&
    typeof body.character === 'string' && body.character.trim() !== '';
  if (!hasCode && !hasAccount) return { status: 422 };
  if (hasCode && body.pob_code.includes('@error:422')) return { status: 422 };
  return { status: 200, summary: structuredClone(summary) };
}

export function createMockServer({ fixturesDir = DEFAULT_FIXTURES_DIR, buildFixture = BUILD_FIXTURE_PATH } = {}) {
  const fixtures = loadFixtures(fixturesDir);
  const buildSummary = loadBuildSummary(buildFixture);
  // TASK-207: the imported build is stored per server instance. Deliberately
  // NOT coupled to POST /diff's 404 path — /diff stays fixture-routed so the
  // TASK-205/206 harness needs no import step; the real no-build coupling
  // lands with server/ in TASK-202.
  let activeBuild = null;
  return http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    const bare = (status) => res.writeHead(status).end(); // RULING-20: error states are status-code only

    if (req.method === 'GET' && pathname === `${CONTRACT_BASE_PATH}/build`) {
      if (activeBuild === null) {
        bare(404); // no build imported (contract 404)
      } else {
        res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(activeBuild));
      }
      return;
    }

    if (req.method === 'POST' && pathname === `${CONTRACT_BASE_PATH}/build`) {
      let raw = '';
      req.on('data', (chunk) => {
        raw += chunk;
        if (raw.length > 1_000_000) req.destroy(); // PoB codes are large; still far above any real one
      });
      req.on('end', () => {
        let body;
        try {
          body = JSON.parse(raw);
        } catch {
          bare(422);
          return;
        }
        const { status, summary } = routeBuild(body, buildSummary);
        if (status === 200) {
          activeBuild = summary; // accepts and stores the fake summary (TASK-207 AC)
          res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(summary));
        } else {
          bare(status);
        }
      });
      return;
    }

    if (req.method !== 'POST' || pathname !== `${CONTRACT_BASE_PATH}/diff`) {
      bare(404); // mock implements only GET/POST /build and POST /diff
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
        bare(422);
        return;
      }
      const { status, card } = route(body, fixtures);
      if (status === 200) {
        res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(card));
      } else {
        bare(status);
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
    console.log(
      `mock POST ${CONTRACT_BASE_PATH}/diff + GET/POST ${CONTRACT_BASE_PATH}/build on http://${host}:${port} ` +
        `(${loadFixtures().size} verdict fixtures + 1 build fixture loaded)`,
    );
  });
}
