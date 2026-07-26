/**
 * TASK-202 readiness smoke test (issue #60): the REAL python server skeleton
 * (server/ — already on main) booted on an ephemeral port, exercised
 * end-to-end through the REAL generated client after a one-line retarget via
 * configureApiClient() — the same client path the web app and overlay use.
 *
 * The skeleton is fixture-backed today (FixtureCalculator); TASK-202b swaps
 * in the real engine without touching this boundary, making this test the
 * integration tripwire for that swap. It also keeps packaging/launch.py's
 * mirrored app construction honest (its own smoke tests cover that side).
 *
 * Requires python3 + pyyaml (repo requirements.txt) — this is a python repo;
 * absence is a hard failure with a clear message, never a silent skip.
 */
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ApiError } from "../src/generated/core/ApiError";
import { OpenAPI } from "../src/generated/core/OpenAPI";
import { DefaultService } from "../src/generated/services/DefaultService";
import { CONTRACT_API_BASE, configureApiClient } from "../src/lib/apiBase";

const REPO_ROOT = join(import.meta.dirname, "..", "..");

/** Mirror of server/__main__.py construction, on an ephemeral port. */
const BOOT = String.raw`
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from server.app import ApiApplication, create_server
from server.assumptions import AssumptionsEvaluator
from server.calculator import FixtureCalculator
app = ApiApplication(
    FixtureCalculator(root / "contracts" / "fixtures"),
    AssumptionsEvaluator(root / "assumptions"),
)
srv = create_server(app, "127.0.0.1", 0)
print(srv.server_address[1], flush=True)
srv.serve_forever()
`;

function ensurePython(): void {
  const probe = spawnSync("python3", ["-c", "import yaml"], { stdio: "ignore" });
  if (probe.error || probe.status !== 0) {
    throw new Error(
      "serverSkeleton smoke test requires python3 + pyyaml (see repo requirements.txt)",
    );
  }
}

function bootSkeleton(): Promise<{ child: ChildProcess; base: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", ["-c", BOOT, REPO_ROOT], { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`skeleton did not report a port within 15s. stderr: ${stderr}`));
    }, 15_000);
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

describe("server skeleton smoke test — generated client vs real server/ (issue #60)", () => {
  let child: ChildProcess;

  beforeAll(async () => {
    ensurePython();
    const booted = await bootSkeleton();
    child = booted.child;
    configureApiClient(booted.base);
  }, 30_000);

  afterAll(async () => {
    OpenAPI.BASE = CONTRACT_API_BASE;
    if (child && !child.killed) {
      child.kill("SIGTERM");
      await new Promise((resolve) => child.once("exit", resolve));
    }
  });

  it("GET /build is an honest 404 before any import", async () => {
    const err = await DefaultService.getActiveBuild().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
  });

  it("POST /build imports and summarizes the build", async () => {
    // Contract-shaped request only (oneOf pob_code | account+character) — the
    // skeleton infers the skill from the @skill marker; no invented fields.
    const summary = await DefaultService.importBuild({
      pob_code: "@skill:Frostbolt;@tag:chill",
    });
    expect(summary.build_id).toMatch(/^b-/);
    expect(summary.main_skill.name).toBe("Frostbolt");
    expect(summary.main_skill.inferred).toBe(true);
    expect(summary.preset_default).toBe("mapping");
    // …and the summary is the server's stored truth afterwards.
    const active = await DefaultService.getActiveBuild();
    expect(active.build_id).toBe(summary.build_id);
  });

  it("POST /diff returns the fixture-backed verdict card", async () => {
    const card = await DefaultService.diffItem({ item_text: "Rarity: RARE\n@fixture:upgrade_mapping" });
    expect(card.verdict).toBe("UPGRADE");
    expect(card.offense_delta_pct).toBe(12.4);
    expect(card.assumptions.map((a) => a.id)).toContain("config.flasks_up");
    expect(card.preset).toBe("mapping");
  });

  it("chip-override round-trips through the skeleton (I3)", async () => {
    const card = await DefaultService.diffItem({
      item_text: "@fixture:upgrade_mapping",
      overrides: [{ assumption_id: "config.flasks_up", value: false }],
    });
    const flasks = card.assumptions.find((a) => a.id === "config.flasks_up");
    expect(flasks?.value).toBe(false);
  });

  it("honest failure modes: unknown fixture and bogus preset are 422", async () => {
    const unknown = await DefaultService.diffItem({ item_text: "@fixture:no_such_fixture" }).catch(
      (e: unknown) => e,
    );
    expect(unknown).toBeInstanceOf(ApiError);
    expect((unknown as ApiError).status).toBe(422);

    const preset = await DefaultService.diffItem({
      item_text: "@fixture:upgrade_mapping",
      preset: "bogus" as never, // deliberate contract violation → server must reject
    }).catch((e: unknown) => e);
    expect(preset).toBeInstanceOf(ApiError);
    expect((preset as ApiError).status).toBe(422);
  });
});
