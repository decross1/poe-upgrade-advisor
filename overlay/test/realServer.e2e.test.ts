/**
 * TASK-210-S6 (issue #79): the OVERLAY's production pipeline against the REAL
 * server + engine. Every other overlay test stubs postDiff or the fixture
 * mock; this suite drives the exact composition src/main.ts wires —
 * createClipboardPipeline(real createDiffFlow, real
 * bindGeneratedDiff(resolveServerBaseUrl(env))) — with ONLY the clipboard
 * source stubbed (the one seam Electron owns), against `python3 -m server`
 * (PobCalculator + AssumptionsEvaluator) on an ephemeral port.
 *
 * The server lifecycle is copied from web/test/realServer.e2e.test.tsx (same
 * BOOT construction, same golden corpus PoB code, same availability policy) —
 * do not invent a second one.
 *
 * Golden inputs (read-only): the corpus seed
 * engine/corpus/seed/ninja/12-elementalist-ci-cold-snap.json's
 * `pathOfBuildingExport` code, and engine/tests/fixtures/item.txt — the same
 * pair engine/tests/test_server_adapter.py pins.
 *
 * Clipboard text note: the production watcher only emits text carrying the
 * game's stable two-line header (`Item Class:` + `Rarity:`), which the
 * engine's golden fixture (PoB export format) omits. Real in-game-format
 * clipboard text — `--------` separators, (implicit) tags, server-side
 * canonicalization — is issue #119's seam, backend-owned, and deliberately
 * NOT this stage's job. To stay independent of it this suite wraps the
 * existing golden item in the minimal header the watcher recognizes;
 * verified against the real engine: PoB's Item parser skips the header line
 * and returns the byte-identical card (same diff_id) as for the bare
 * fixture. The pipeline forwards text unchanged, so the server receives the
 * wrapped text and the direct-client comparison below uses it too.
 *
 * Requires python3 + pyyaml and the pinned engine runtime
 * (engine/runtime/build.sh + the engine/vendor/PathOfBuilding submodule). A
 * missing runtime skips the suite LOUDLY (banner below + vitest-reported
 * skips) — never a silent pass.
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { OpenAPI } from "../../web/src/generated/core/OpenAPI";
import { DefaultService } from "../../web/src/generated/services/DefaultService";
import { createClipboardPipeline, type ClipboardPipeline } from "../src/clipboardPipeline";
import { bindGeneratedDiff } from "../src/diffRequest";
import { resolveServerBaseUrl } from "../src/serverEndpoint";
import type { ShellState } from "../src/shellState";

const REPO_ROOT = join(import.meta.dirname, "..", "..");
const GOLDEN_ITEM = readFileSync(
  join(REPO_ROOT, "engine", "tests", "fixtures", "item.txt"),
  "utf8",
);
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

/** Golden item in the minimal clipboard envelope the watcher recognizes. */
const CLIPBOARD_ITEM_TEXT =
  "Item Class: Shields\r\n" + GOLDEN_ITEM.replace(/\r?\n/g, "\r\n");

/**
 * Passes the watcher's header recognition but names a base Path of Building
 * cannot resolve — the honest 422 → ERROR_UNPARSEABLE leg (RULING-20 keys
 * off the status code only).
 */
const UNPARSEABLE_ITEM_TEXT =
  "Item Class: Wands\r\nRarity: Rare\r\nTotally Bogusname\r\nNotareal Base\r\n" +
  "--------\r\nnothing real here\r\n";

const strictSchema = JSON.parse(
  readFileSync(join(REPO_ROOT, "contracts", "verdict.schema.json"), "utf8"),
);
const ajvStrict = new Ajv2020({ strict: true, allErrors: true });
const validateCard: ValidateFunction = ajvStrict.compile(strictSchema);

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
  const probe = spawnSync("python3", ["-c", "import yaml"], { stdio: "ignore" });
  if (probe.error || probe.status !== 0) {
    throw new Error(
      "real-server E2E requires python3 + pyyaml (see repo requirements.txt)",
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
      "realServer E2E SKIPPED: pinned engine runtime not found.",
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

const ORIGINAL_API_BASE = OpenAPI.BASE;
const pipelines: ClipboardPipeline[] = [];
afterEach(() => {
  for (const pipeline of pipelines.splice(0)) pipeline.stop();
});

describe.skipIf(!RUNTIME_OK)(
  "real-server E2E — overlay production pipeline vs the real engine (TASK-210-S6, issue #79)",
  () => {
    let child: ChildProcess;
    let base: string;

    beforeAll(async () => {
      ensurePython();
      const booted = await bootRealServer();
      child = booted.child;
      base = booted.base;
      console.warn(`[E2E] real server booted at ${base}`);
    }, 90_000);

    afterAll(async () => {
      OpenAPI.BASE = ORIGINAL_API_BASE;
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

    /**
     * The production composition from src/main.ts, headless: real watcher,
     * real diffFlow, real generated-client postDiff bound through
     * resolveServerBaseUrl — only the clipboard source is a stub. A long
     * pollMs keeps sampling manual (pollNow), exactly as the Stage-1 suite.
     */
    function startPipeline(states: ShellState[]): {
      pipeline: ClipboardPipeline;
      clipboard: { text: string; readText: () => string };
    } {
      const clipboard = { text: "", readText: () => clipboard.text };
      const pipeline = createClipboardPipeline({
        clipboard,
        postDiff: bindGeneratedDiff(
          resolveServerBaseUrl({ POE_ADVISOR_SERVER_URL: base }),
        ),
        onState: (state) => states.push(state),
        pollMs: 60_000,
      });
      pipelines.push(pipeline);
      pipeline.start();
      return { pipeline, clipboard };
    }

    it("a capture BEFORE any build is imported yields ERROR_NO_BUILD", async () => {
      const states: ShellState[] = [];
      const { pipeline, clipboard } = startPipeline(states);

      clipboard.text = CLIPBOARD_ITEM_TEXT;
      await pipeline.pollNow();

      // 404 → no_build (RULING-20: status code only, body never parsed).
      expect(states.map((s) => s.kind)).toEqual(["LOADING", "ERROR_NO_BUILD"]);
    }, 15_000);

    it("imports the golden corpus build through the generated client", async () => {
      const summary = await DefaultService.importBuild({
        pob_code: GOLDEN_POB_CODE,
      });
      expect(summary.character_class).toBe("Witch");
      expect(summary.ascendancy).toBe("Elementalist");
      expect(summary.level).toBe(97);
      expect(summary.main_skill.name).toContain("Cold Snap");
    }, 30_000);

    it("golden item capture flows LOADING → VERDICT with the engine's real card", async () => {
      const states: ShellState[] = [];
      const { pipeline, clipboard } = startPipeline(states);

      const started = performance.now();
      clipboard.text = CLIPBOARD_ITEM_TEXT;
      await pipeline.pollNow();
      console.warn(
        `[E2E] overlay clipboard→verdict through the real engine: ${(performance.now() - started).toFixed(1)} ms`,
      );

      expect(states.map((s) => s.kind)).toEqual(["LOADING", "VERDICT"]);
      const terminal = states[1];
      if (terminal.kind !== "VERDICT") {
        throw new Error("unreachable: sequence asserted above");
      }
      const card = terminal.card;

      // Contract: the pipeline's card validates against verdict.schema.json.
      expect(
        validateCard(card),
        `pipeline verdict failed verdict.schema.json: ${ajvStrict.errorsText(validateCard.errors)}`,
      ).toBe(true);

      // The deltas are the engine's real numbers: asserted against the
      // response body of the same /diff through the generated client, never
      // against a hardcoded fixture card.
      const response = await DefaultService.diffItem({
        item_text: CLIPBOARD_ITEM_TEXT,
      });
      expect(card.diff_id).toBe(response.diff_id);
      expect(card.verdict).toBe(response.verdict);
      expect(card.offense_delta_pct).toBe(response.offense_delta_pct);
      expect(card.defense_delta_pct).toBe(response.defense_delta_pct);
      console.warn(
        `[E2E] overlay pipeline rendered REAL verdict: ${card.verdict} ` +
          `offense ${card.offense_delta_pct}% defense ${card.defense_delta_pct}% ` +
          `(${card.diff_id})`,
      );
    }, 15_000);

    it("unreadable text yields ERROR_UNPARSEABLE", async () => {
      const states: ShellState[] = [];
      const { pipeline, clipboard } = startPipeline(states);

      clipboard.text = UNPARSEABLE_ITEM_TEXT;
      await pipeline.pollNow();

      // 422 → unparseable (RULING-20: status code only).
      expect(states.map((s) => s.kind)).toEqual([
        "LOADING",
        "ERROR_UNPARSEABLE",
      ]);
    }, 15_000);
  },
);
