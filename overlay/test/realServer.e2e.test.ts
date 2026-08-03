/**
 * TASK-212-S1 E2E (issue #97): the OVERLAY's own path against the REAL
 * server + engine — the exact `python3 -m server` construction
 * (PobCalculator + AssumptionsEvaluator) on an ephemeral port, driven
 * through the shell's real composition:
 *
 *   createClipboardPipeline({ clipboard, postDiff: bindGeneratedDiff(base) })
 *
 * — the same watcher → diffFlow → generated-client wiring main.ts uses, with
 * only the OS clipboard adapter faked. No stubbed fetch, no fixture verdict,
 * no hand-rolled body: /build and every /diff go over real HTTP to the real
 * engine — the first proof a copied item yields a real verdict on this path.
 *
 * Spawn/readiness/teardown are COPIED from web/test/realServer.e2e.test.tsx
 * (TASK-208): duplication across the package boundary is deliberate (AC-1).
 * Golden inputs (read-only): the corpus seed 12-elementalist-ci-cold-snap
 * .json's `pathOfBuildingExport` and engine/tests/fixtures/item.txt — the
 * pair the web E2E and engine/tests/test_server_adapter.py pin. The fixture
 * is trimmed of the game's first Ctrl+C line; an in-game copy of this Vaal
 * Spirit Shield begins with "Item Class: Shields", which the shell's watcher
 * (S1: recognition only) requires — the test re-attaches exactly that line.
 *
 * Schema validation uses the repo-pinned python jsonschema (requirements.txt)
 * against contracts/verdict.schema.json — the overlay package carries no JS
 * schema validator and the packet scope forbids adding one.
 *
 * Availability policy mirrors the web E2E exactly: missing python3/pyyaml/
 * jsonschema is a hard failure; a missing pinned engine runtime skips the
 * suite LOUDLY (banner below + vitest-reported skips), never silently.
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ApiError } from "../../web/src/generated/core/ApiError";
import { OpenAPI } from "../../web/src/generated/core/OpenAPI";
import { DefaultService } from "../../web/src/generated/services/DefaultService";
import {
  createClipboardPipeline,
  type ClipboardPipeline,
} from "../src/clipboardPipeline";
import { bindGeneratedDiff, type PostDiff } from "../src/diffRequest";
import { CONTRACT_SERVER_URL } from "../src/serverEndpoint";
import type { ShellState } from "../src/shellState";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const GOLDEN_ITEM_BODY = readFileSync(
  join(REPO_ROOT, "engine", "tests", "fixtures", "item.txt"),
  "utf8",
);
// The real in-game Ctrl+C of this item, header line included (see header).
const GOLDEN_ITEM = `Item Class: Shields\r\n${GOLDEN_ITEM_BODY}`;
const GOLDEN_POB_CODE = (
  JSON.parse(
    readFileSync(
      join(
        REPO_ROOT,
        "engine",
        "corpus",
        "seed",
        "ninja",
        "12-elementalist-ci-cold-snap.json",
      ),
      "utf8",
    ),
  ) as { pathOfBuildingExport: string }
).pathOfBuildingExport;

const SCHEMA_PATH = join(REPO_ROOT, "contracts", "verdict.schema.json");
const FIXTURE_CARDS: unknown[] = [
  "upgrade_mapping.json",
  "downgrade_mapping.json",
  "sidegrade_bossing.json",
  "cant_evaluate_trigger_build.json",
].map((n) => JSON.parse(readFileSync(join(REPO_ROOT, "contracts", "fixtures", n), "utf8")));

/** jsonschema validator_for: honors whichever draft the contract declares. */
const VALIDATE_PY = String.raw`
import json, sys
from jsonschema import validators
schema = json.load(open(sys.argv[1], encoding="utf-8"))
card = json.load(sys.stdin)
cls = validators.validator_for(schema)
cls.check_schema(schema)
errors = sorted(cls(schema).iter_errors(card), key=lambda e: list(e.path))
for e in errors:
    print("/".join(map(str, e.path)) or "<root>", e.message, file=sys.stderr)
sys.exit(1 if errors else 0)
`;

function expectSchemaValid(card: unknown): void {
  const res = spawnSync("python3", ["-c", VALIDATE_PY, SCHEMA_PATH], {
    input: JSON.stringify(card),
    encoding: "utf8",
  });
  expect(res.status, `verdict failed contracts/verdict.schema.json:\n${res.stderr}`).toBe(0);
}

/** Mirror of server/__main__.py construction, on an ephemeral port. */
const BOOT = String.raw`
import signal
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from server.app import ApiApplication, create_server
from server.assumptions import AssumptionsEvaluator
from server.calculator import PobCalculator
calculator = PobCalculator(root)
app = ApiApplication(
    calculator,
    AssumptionsEvaluator(root / "assumptions"),
)
srv = create_server(app, "127.0.0.1", 0)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
print(srv.server_address[1], flush=True)
try:
    srv.serve_forever()
finally:
    srv.server_close()
    calculator.close()
`;

function ensurePython(): void {
  const probe = spawnSync("python3", ["-c", "import yaml, jsonschema"], {
    stdio: "ignore",
  });
  if (probe.error || probe.status !== 0) {
    throw new Error(
      "real-server E2E requires python3 + pyyaml + jsonschema (see repo requirements.txt)",
    );
  }
}

/** Mirror of engine/tests/test_server_adapter.py's runtime_is_available(). */
function runtimeAvailable(): boolean {
  if (process.env.POBCALC_LUA && process.env.POBCALC_LUA_CPATH) return true;
  const runtimeRoot =
    process.env.POBCALC_RUNTIME ?? join(REPO_ROOT, "engine", ".runtime");
  return (
    existsSync(join(runtimeRoot, "bin", "luajit")) &&
    existsSync(join(runtimeRoot, "lib", "lua", "5.1", "lua-utf8.so"))
  );
}

const RUNTIME_OK = runtimeAvailable();
if (!RUNTIME_OK) {
  console.warn(
    [
      "==============================================================",
      "overlay realServer E2E SKIPPED: pinned engine runtime not found.",
      "Build it with: engine/runtime/build.sh (plus `git submodule",
      "update --init engine/vendor/PathOfBuilding`), or set",
      "POBCALC_RUNTIME / POBCALC_LUA + POBCALC_LUA_CPATH.",
      "==============================================================",
    ].join("\n"),
  );
}

function bootRealServer(): Promise<{ child: ChildProcess; base: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", ["-c", BOOT, REPO_ROOT], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    // The port line prints only after PobCalculator has spawned the pobcalc
    // worker and pinged it — i.e. the engine is warm. Cold PoB start takes
    // seconds; 60s is generous headroom, never an infinite hang.
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(
        new Error(
          `real server did not report a port within 60s. stderr: ${stderr}`,
        ),
      );
    }, 60_000);
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      const line = stdout.split("\n", 1)[0].trim();
      if (/^\d+$/.test(line)) {
        clearTimeout(timer);
        resolve({ child, base: `http://127.0.0.1:${line}/api/v0` });
      }
    });
  });
}

describe.skipIf(!RUNTIME_OK)(
  "real-server E2E — overlay clipboard pipeline vs the real engine (TASK-212-S1, issue #97)",
  () => {
    let child: ChildProcess;
    let postDiff: PostDiff;
    const pipelines: ClipboardPipeline[] = [];

    beforeAll(async () => {
      ensurePython();
      const booted = await bootRealServer();
      child = booted.child;
      // The shell's only /diff call site (diffRequest.ts): binds the shared
      // generated client at baseUrl — the real client boundary, not a stub.
      postDiff = bindGeneratedDiff(booted.base);
      console.warn(`[E2E] real server booted at ${booted.base}`);
    }, 90_000);

    afterAll(async () => {
      for (const pipeline of pipelines.splice(0)) pipeline.stop();
      OpenAPI.BASE = CONTRACT_SERVER_URL;
      if (child && !child.killed) {
        child.kill("SIGTERM");
        const exited = await Promise.race([
          new Promise((resolve) => child.once("exit", resolve)).then(
            () => true,
          ),
          new Promise((resolve) => setTimeout(() => resolve(false), 10_000)),
        ]);
        if (!exited) child.kill("SIGKILL");
      }
    });

    it("GET /build is an honest 404 before any import", async () => {
      const err = await DefaultService.getActiveBuild().catch(
        (e: unknown) => e,
      );
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
    });

    it("imports the golden PoB code via POST /build (real engine parse)", async () => {
      const started = performance.now();
      const summary = await DefaultService.importBuild({
        pob_code: GOLDEN_POB_CODE,
      });
      console.warn(
        `[E2E] overlay build import: ${(performance.now() - started).toFixed(1)} ms`,
      );
      // PoB-confirmed identity of the golden build.
      expect(summary.character_class).toBe("Witch");
      expect(summary.ascendancy).toBe("Elementalist");
      expect(summary.level).toBe(97);
      expect(summary.main_skill.name).toContain("Cold Snap");
    }, 30_000);

    it("a clipboard capture of the golden item emits the real engine verdict — schema-valid, not a fixture, deterministic", async () => {
      const clipboard = {
        text: "a whisper from a trade request",
        readText: () => clipboard.text,
      };
      const states: ShellState[] = [];
      const pipeline = createClipboardPipeline({
        clipboard,
        postDiff,
        onState: (state) => states.push(state),
        pollMs: 60_000, // manual pollNow only — never a background timer
      });
      pipelines.push(pipeline);
      pipeline.start();

      // The game's Ctrl+C: watcher recognizes the header; one /diff over real HTTP (S2).
      clipboard.text = GOLDEN_ITEM;
      await pipeline.pollNow();

      expect(states.map((s) => s.kind)).toEqual(["LOADING", "VERDICT"]);
      const card = states.flatMap((s) => (s.kind === "VERDICT" ? [s.card] : []))[0];
      console.warn(
        `[E2E] overlay pipeline emitted REAL-VERDICT-JSON:${JSON.stringify(card)}`,
      );

      // Valid against contracts/verdict.schema.json via the real validator (I2 caps are schema-enforced).
      expectSchemaValid(card);

      // Real engine output: none of the shipped contract fixtures (every other overlay test mocks these).
      for (const fixture of FIXTURE_CARDS) {
        expect(card, "overlay emitted a contracts/fixtures golden — NOT a real engine verdict").not.toEqual(fixture);
      }

      // Engine-identity pins (as the web E2E): build-default preset, server diff id, every assumption visible (I3).
      expect(card.preset).toBe("mapping");
      expect(card.diff_id).toMatch(/^d-/);
      expect(card.assumptions.length).toBeGreaterThan(0);
      for (const a of card.assumptions) {
        expect(a.id).toBeTruthy();
        expect(a.label).toBeTruthy();
        expect(a).toHaveProperty("value");
      }

      // Deterministic across two calls: an unrelated clipboard change is ignored, then a
      // second copy starts a fresh session (RULING-18) and the engine returns an identical card.
      clipboard.text = "stash tab name copied by accident";
      await pipeline.pollNow();
      clipboard.text = GOLDEN_ITEM;
      await pipeline.pollNow();

      expect(states.map((s) => s.kind)).toEqual(["LOADING", "VERDICT", "LOADING", "VERDICT"]);
      const allCards = states.flatMap((s) => (s.kind === "VERDICT" ? [s.card] : []));
      expect(allCards).toHaveLength(2);
      expect(allCards[1]).toEqual(allCards[0]);
    }, 20_000);
  },
);
