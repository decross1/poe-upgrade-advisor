/**
 * TASK-208 E2E (issue #36): the REAL server + engine — booted with the exact
 * `python3 -m server` construction (PobCalculator + AssumptionsEvaluator,
 * server/__main__.py) on an ephemeral port — driven end-to-end two ways:
 *
 *   1. VIA THE WEB UI: the rendered demo App (no seams stubbed — the real
 *      generated client) imports the golden corpus PoB code through
 *      BuildImport, then the golden item PASTED INTO THE PASTE BOX (the
 *      player's own path, TASK-211-S1) renders the engine's real verdict
 *      card with its assumptions chips (I3).
 *   2. Via the generated client directly: schema-valid deterministic verdict
 *      (captured to the run log as evidence), chip-override round-trip (I3),
 *      honest 404/422 failure modes.
 *
 * TASK-214-S2 (issue #125) adds the Tier-2 proof: the card's one details
 * affordance is clicked against the REAL server and the panel must render the
 * live GET /breakdown/{diff_id} drivers measured from the pasted item — never
 * a web/mock fixture — schema-validated against the contract's Breakdown
 * schema, with the unknown-diff_id 404 rendering the panel's honest copy (I5).
 *
 * Supersedes the TASK-202 serverSkeleton smoke test: that tripwire targeted
 * the fixture-backed skeleton (FixtureCalculator), which TASK-202b (PR #63)
 * removed — the swap it guarded has landed, and this is the same boundary
 * test against the real engine.
 *
 * Golden inputs (read-only): the corpus seed
 * engine/corpus/seed/ninja/12-elementalist-ci-cold-snap.json's
 * `pathOfBuildingExport` code, and engine/tests/fixtures/item.txt — the same
 * pair engine/tests/test_server_adapter.py pins, so the engine side already
 * proves this import+diff pair against the real worker.
 *
 * Requires python3 + pyyaml (hard failure with a clear message, never a
 * silent skip) and the pinned engine runtime (engine/runtime/build.sh + the
 * engine/vendor/PathOfBuilding submodule). A missing runtime skips the suite
 * LOUDLY (banner below + vitest-reported skips) — the same availability
 * policy as engine/tests/test_server_adapter.py.
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv";
import { parse as parseYaml } from "yaml";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ApiError } from "../src/generated/core/ApiError";
import { CancelablePromise } from "../src/generated/core/CancelablePromise";
import { OpenAPI } from "../src/generated/core/OpenAPI";
import { DefaultService } from "../src/generated/services/DefaultService";
import { CONTRACT_API_BASE, configureApiClient } from "../src/lib/apiBase";
import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";
import type { DiffFn } from "../src/session/useCardSession";
import { App } from "../src/demo/App";

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

const strictSchema = JSON.parse(
  readFileSync(join(REPO_ROOT, "contracts", "verdict.schema.json"), "utf8"),
);
const ajvStrict = new Ajv2020({ strict: true, allErrors: true });
const validateCard: ValidateFunction = ajvStrict.compile(strictSchema);

// TASK-214-S2: the contract's Breakdown schema (components.schemas.Breakdown
// in contracts/openapi.yaml), compiled with the same Ajv setup as VerdictCard
// — the boundary assertion for the live GET /breakdown/{diff_id} response.
// The YAML flow-mapping `description: e.g. total_dps, ehp` parses a spurious
// null-valued `ehp` key (the comma splits the scalar); JSON Schema has no
// null-valued keywords (`type: null` is the STRING "null"), so stripping
// nulls is a safe de-quirk and keeps Ajv strict mode meaningful.
const openapiDoc = parseYaml(
  readFileSync(join(REPO_ROOT, "contracts", "openapi.yaml"), "utf8"),
) as { components: { schemas: { Breakdown: unknown } } };
const breakdownSchema = JSON.parse(
  JSON.stringify(openapiDoc.components.schemas.Breakdown, (_key, value: unknown) =>
    value === null ? undefined : value,
  ),
) as Record<string, unknown>;
const validateBreakdown: ValidateFunction =
  ajvStrict.compile(breakdownSchema);

// Every driver in every web/mock breakdown fixture, for the NEGATIVE
// provenance check: no driver the live server returns may equal one of these
// {mod_text, contribution_pct, stat} triples. (Read-only; a fixture may never
// SATISFY an assertion here — it can only falsify one.)
const MOCK_FIXTURE_DRIVERS: readonly unknown[] = readdirSync(
  join(REPO_ROOT, "web", "mock", "fixtures", "breakdown"),
)
  .filter((name) => name.endsWith(".json"))
  .flatMap(
    (name) =>
      (
        JSON.parse(
          readFileSync(
            join(REPO_ROOT, "web", "mock", "fixtures", "breakdown", name),
            "utf8",
          ),
        ) as { drivers?: unknown[] }
      ).drivers ?? [],
  );

// The card's two bars are computed from exactly these stats
// (server/app.py: offense = total_dps delta, defense = ehp delta), so a
// driver stat the card reported is one of these two.
const CARD_REPORTED_STATS: readonly string[] = ["total_dps", "ehp"];

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

describe.skipIf(!RUNTIME_OK)(
  "real-server E2E — web UI + generated client vs the real engine (TASK-208, issue #36)",
  () => {
    let child: ChildProcess;

    beforeAll(async () => {
      ensurePython();
      const booted = await bootRealServer();
      child = booted.child;
      configureApiClient(booted.base);
      console.warn(`[E2E] real server booted at ${booted.base}`);
    }, 90_000);

    afterAll(async () => {
      OpenAPI.BASE = CONTRACT_API_BASE;
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

    it("imports the golden PoB code VIA THE WEB UI (BuildImport → POST /build)", async () => {
      render(<App />);

      // TASK-211-S1: the page starts with an empty paste box and issues NO
      // request on mount — there is no verdict card before a player submit.
      expect(document.querySelector(".verdict-card")).toBeNull();

      const started = performance.now();
      fireEvent.change(screen.getByLabelText("Path of Building code or XML"), {
        target: { value: GOLDEN_POB_CODE },
      });
      fireEvent.click(screen.getByRole("button", { name: "Import build" }));

      await screen.findByText("Build imported", {}, { timeout: 20_000 });
      const importMs = performance.now() - started;
      console.warn(`[E2E] build import via web UI: ${importMs.toFixed(1)} ms`);

      // PoB-confirmed identity rendered in the success summary.
      const summary = screen.getByRole("status");
      expect(summary.textContent).toContain("Witch (Elementalist)");
      expect(summary.textContent).toContain("97");
      expect(summary.textContent).toContain("Vaal Cold Snap");
    }, 30_000);

    it("an item pasted into the paste box renders the real engine verdict in the UI", async () => {
      // Fresh harness against the already-imported server session (the build
      // imported via the UI above persists server-side). The player's path
      // (TASK-211-S1): paste item text into the box, one explicit submit.
      render(<App />);
      // AC-4: no card and no /diff request until the player submits.
      expect(document.querySelector(".verdict-card")).toBeNull();

      const box = screen.getByLabelText(/Item text/);
      const submit = screen.getByRole("button", { name: "Evaluate item" });

      // I5 through the UI: unreadable text is never pre-judged in the client —
      // it goes to the server, whose honest 422 renders the unparseable panel.
      fireEvent.change(box, { target: { value: "???" } });
      fireEvent.click(submit);
      await screen.findByText(/Couldn't read that item/, {}, { timeout: 15_000 });

      // The golden item through the same paste box renders the real verdict.
      fireEvent.change(box, { target: { value: GOLDEN_ITEM } });
      fireEvent.click(submit);

      const card = await screen.findByLabelText(
        "Upgrade verdict",
        {},
        { timeout: 15_000 },
      );
      const word = card.querySelector(".verdict-word")?.textContent ?? "";
      expect(word).toMatch(/^(UPGRADE|SIDEGRADE|DOWNGRADE|CAN'T EVALUATE)$/);
      console.warn(`[E2E] web UI rendered verdict word: ${word}`);

      // I2/I3: two deltas, the sentence, and every assumption as a chip.
      expect(within(card).getByText("Offense")).toBeTruthy();
      expect(within(card).getByText("Defense")).toBeTruthy();
      const chips = within(card).getByRole("group", { name: "Assumptions" });
      expect(chips.querySelectorAll(".chip").length).toBeGreaterThan(0);
      // The one details affordance exists (I7).
      expect(
        within(card).getByRole("link", { name: /details/i }),
      ).toBeTruthy();
    }, 20_000);

    it("the details affordance renders the LIVE server's drivers for the pasted item (Tier-2, TASK-214-S2)", async () => {
      render(<App />);
      fireEvent.change(screen.getByLabelText(/Item text/), {
        target: { value: GOLDEN_ITEM },
      });
      fireEvent.click(screen.getByRole("button", { name: "Evaluate item" }));
      const card = await screen.findByLabelText(
        "Upgrade verdict",
        {},
        { timeout: 15_000 },
      );

      // The same tap a player makes (I7): one tap = one GET
      // /breakdown/{diff_id} against the live server.
      fireEvent.click(within(card).getByRole("link", { name: /details/i }));

      const driversSection = await screen.findByLabelText(
        "Top stat drivers",
        {},
        { timeout: 15_000 },
      );
      const rows = within(driversSection).getAllByRole("row").slice(1); // header row
      expect(rows.length).toBeGreaterThan(0);
      const rendered = rows.map((row) => {
        const cells = within(row).getAllByRole("cell");
        return {
          modText: cells[0].textContent ?? "",
          stat: cells[1].textContent ?? "",
        };
      });
      console.warn(`[E2E] live Tier-2 drivers: ${JSON.stringify(rendered)}`);

      // AC-1: at least one rendered driver is the SERVER's — its mod_text is a
      // line of the item the player pasted and its stat is one the card's two
      // bars reported. No mock fixture mod_text appears in this item, so this
      // cannot be satisfied by fixture data.
      const proven = rendered.filter(
        (d) =>
          d.modText.length > 0 &&
          GOLDEN_ITEM.includes(d.modText) &&
          CARD_REPORTED_STATS.includes(d.stat),
      );
      expect(
        proven.length,
        `no rendered driver traced to the pasted item + card stats; rows: ${JSON.stringify(rendered)}`,
      ).toBeGreaterThan(0);
    }, 20_000);

    it("GET /breakdown/{diff_id} is schema-valid and measured from this item (TASK-214-S2)", async () => {
      const card = await DefaultService.diffItem({ item_text: GOLDEN_ITEM });
      const breakdown = await DefaultService.getBreakdown(card.diff_id);
      console.warn(`[E2E] REAL-BREAKDOWN-JSON:${JSON.stringify(breakdown)}`);

      // AC-2: contract shape at the boundary, validated with the same Ajv
      // setup this suite uses for VerdictCard.
      expect(
        validateBreakdown(breakdown),
        `real breakdown failed the contract Breakdown schema: ${ajvStrict.errorsText(validateBreakdown.errors)}`,
      ).toBe(true);
      expect(breakdown.diff_id).toBe(card.diff_id);
      expect(breakdown.drivers.length).toBeGreaterThan(0);

      // Provenance: drivers are measured from THIS item (leave-one-out,
      // TASK-214-S1) — at least one mod_text is a pasted item line, and no
      // driver equals a mock fixture's {mod_text, contribution_pct, stat}.
      const fromItem = breakdown.drivers.filter((d) =>
        GOLDEN_ITEM.includes(d.mod_text),
      );
      expect(
        fromItem.length,
        `no live driver mod_text appears in the pasted item: ${JSON.stringify(breakdown.drivers)}`,
      ).toBeGreaterThan(0);
      for (const fixtureDriver of MOCK_FIXTURE_DRIVERS) {
        expect(breakdown.drivers).not.toContainEqual(fixtureDriver);
      }
    }, 15_000);

    it("an unknown diff_id renders the panel's honest 404 copy against the real server (I5, TASK-214-S2)", async () => {
      // Client level: the live server answers a bare 404 for a diff_id it
      // never issued.
      const err = await DefaultService.getBreakdown("d-no-such-diff").catch(
        (e: unknown) => e,
      );
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);

      // UI level: a card carrying that unknown diff_id via App's documented
      // diffFn test seam — the CARD is only the vehicle for the id; the
      // breakdown fetch is the default loadBreakdown, i.e. the real generated
      // client against the real server. Nothing on that path is stubbed.
      const unknownCard: VerdictCardData = {
        diff_id: "d-no-such-diff",
        verdict: "SIDEGRADE",
        offense_delta_pct: 1.2,
        defense_delta_pct: -0.8,
        sentence: "Carrier card for the unknown-diff 404 proof.",
        assumptions: [],
        confidence: 0.9,
        preset: "mapping",
      };
      const diff: DiffFn = () =>
        new CancelablePromise<VerdictCardData>((resolve) =>
          resolve(unknownCard),
        );
      render(<App diffFn={diff} />);
      fireEvent.change(screen.getByLabelText(/Item text/), {
        target: { value: "Rarity: RARE\nSpike Candidate\n" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Evaluate item" }));
      const card = await screen.findByLabelText("Upgrade verdict");
      fireEvent.click(within(card).getByRole("link", { name: /details/i }));

      // AC-3: the real 404 renders the panel's exact 404 copy — not a blank
      // or stale panel.
      const alert = await screen.findByRole("alert", {}, { timeout: 15_000 });
      expect(alert.textContent).toBe(
        "Breakdown expired or unknown for this diff.",
      );
    }, 15_000);

    it("POST /diff returns the deterministic, schema-valid real verdict (captured)", async () => {
      // Session continuity: the build the UI leg imported is the active one.
      const active = await DefaultService.getActiveBuild();
      expect(active.character_class).toBe("Witch");
      expect(active.ascendancy).toBe("Elementalist");
      expect(active.level).toBe(97);
      expect(active.main_skill.name).toContain("Cold Snap");

      const started = performance.now();
      const card = await DefaultService.diffItem({ item_text: GOLDEN_ITEM });
      const diffMs = performance.now() - started;
      const again = await DefaultService.diffItem({ item_text: GOLDEN_ITEM });

      // Deterministic: the real engine returns byte-identical cards.
      expect(again).toEqual(card);
      console.warn(
        `[E2E] warm diff: ${diffMs.toFixed(1)} ms — REAL-VERDICT-JSON:` +
          JSON.stringify(card),
      );
      // Warm-engine latency gate, same budget as engine/tests (I6 target).
      expect(diffMs).toBeLessThan(150);

      // Contract: valid against contracts/verdict.schema.json; I2 caps.
      expect(
        validateCard(card),
        `real verdict failed verdict.schema.json: ${ajvStrict.errorsText(validateCard.errors)}`,
      ).toBe(true);
      expect(card.sentence.length).toBeLessThanOrEqual(140);
      expect(card.assumptions.length).toBeLessThanOrEqual(6);
      expect(card.preset).toBe("mapping");
      expect(card.diff_id).toMatch(/^d-/);
      // I3: every assumption is visible — id, label, value all present.
      for (const a of card.assumptions) {
        expect(a.id).toBeTruthy();
        expect(a.label).toBeTruthy();
        expect(a).toHaveProperty("value");
      }
    }, 15_000);

    it("chip-override round-trips through the real engine (I3)", async () => {
      const card = await DefaultService.diffItem({ item_text: GOLDEN_ITEM });
      const booleanChip = card.assumptions.find(
        (a) => typeof a.value === "boolean",
      );
      expect(booleanChip).toBeDefined();

      const flipped = await DefaultService.diffItem({
        item_text: GOLDEN_ITEM,
        overrides: [
          { assumption_id: booleanChip!.id, value: !booleanChip!.value },
        ],
      });
      const flippedChip = flipped.assumptions.find(
        (a) => a.id === booleanChip!.id,
      );
      expect(flippedChip?.value).toBe(!booleanChip!.value);

      // One-tap reversible: a plain re-diff restores the inferred value.
      const restored = await DefaultService.diffItem({
        item_text: GOLDEN_ITEM,
      });
      expect(restored.assumptions.find((a) => a.id === booleanChip!.id)?.value).toBe(
        booleanChip!.value,
      );
    }, 15_000);

    it("honest failure modes: unparseable item and bogus preset are 422", async () => {
      const badItem = await DefaultService.diffItem({
        item_text: "???",
      }).catch((e: unknown) => e);
      expect(badItem).toBeInstanceOf(ApiError);
      expect((badItem as ApiError).status).toBe(422);

      const preset = await DefaultService.diffItem({
        item_text: GOLDEN_ITEM,
        preset: "bogus" as never, // deliberate contract violation → server must reject
      }).catch((e: unknown) => e);
      expect(preset).toBeInstanceOf(ApiError);
      expect((preset as ApiError).status).toBe(422);
    }, 15_000);
  },
);
