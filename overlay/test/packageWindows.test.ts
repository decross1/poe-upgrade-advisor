/**
 * TASK-215-S1 — pins the Windows packaging artifact contract.
 *
 * These tests resolve the packager OPTION OBJECT and exported constants only;
 * they never run the packager (it downloads the ~100 MB Electron win32-x64
 * binary on first real run, and tests must not touch the network). The real
 * run is proven by pasted PR evidence (packet AC-5), not by CI.
 *
 * The directory and executable name are a cross-stage contract:
 * packaging/launch.py (TASK-215-S2) and scripts/package_mvp_windows.ps1
 * (TASK-215-S3) hardcode them, so they are pinned here.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import pkg from "../package.json";
// @ts-expect-error -- plain .mjs entrypoint ships no declarations; values asserted below.
import { APP_NAME, ARCH, OUT_DIR, PACKAGED_APP_DIR, PACKAGED_EXE_PATH, PLATFORM, packagerOptions, shouldIgnore } from "../package.mjs";

const OVERLAY_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

describe("artifact contract (cross-stage: launch.py + package_mvp_windows.ps1)", () => {
  it("pins the app name, output dir and packaged exe path", () => {
    expect(APP_NAME).toBe("PoEUpgradeAdvisorOverlay");
    expect(OUT_DIR).toBe("dist-win");
    expect(PLATFORM).toBe("win32");
    expect(ARCH).toBe("x64");
    expect(PACKAGED_APP_DIR).toBe("PoEUpgradeAdvisorOverlay-win32-x64");
    expect(PACKAGED_EXE_PATH).toBe(
      "dist-win/PoEUpgradeAdvisorOverlay-win32-x64/PoEUpgradeAdvisorOverlay.exe",
    );
  });

  it("targets win32/x64 with asar and overwrite, writing under overlay/dist-win/", () => {
    const options = packagerOptions();
    expect(options.platform).toBe("win32");
    expect(options.arch).toBe("x64");
    expect(options.asar).toBe(true);
    expect(options.overwrite).toBe(true);
    expect(options.name).toBe(APP_NAME);
    expect(options.out).toBe(path.join(OVERLAY_DIR, "dist-win"));
  });

  it("sets no icon and no win32metadata (no rcedit/wine dependency)", () => {
    const options = packagerOptions();
    expect(options).not.toHaveProperty("icon");
    expect(options).not.toHaveProperty("win32metadata");
  });
});

describe("runtime-only payload", () => {
  it("includes dist/ and package.json", () => {
    expect(shouldIgnore("/package.json")).toBe(false);
    expect(shouldIgnore("/dist")).toBe(false);
    expect(shouldIgnore("/dist/main.cjs")).toBe(false);
    expect(shouldIgnore("/dist/renderer.js")).toBe(false);
    expect(shouldIgnore("/dist/index.html")).toBe(false);
  });

  it("excludes sources, tests, bench, node_modules and toolchain files", () => {
    for (const p of [
      "/src",
      "/src/main.ts",
      "/test",
      "/test/packageWindows.test.ts",
      "/bench",
      "/bench/latency.mjs",
      "/node_modules",
      "/node_modules/react/index.js",
      "/build.mjs",
      "/package.mjs",
      "/tsconfig.json",
      "/vitest.config.ts",
      "/dist-win",
    ]) {
      expect(shouldIgnore(p), p).toBe(true);
    }
  });

  it("tolerates windows-style separators", () => {
    expect(shouldIgnore("\\dist\\main.cjs")).toBe(false);
    expect(shouldIgnore("\\src\\main.ts")).toBe(true);
  });
});

describe("npm wiring", () => {
  it("package:win runs the existing build first, then the packager entrypoint", () => {
    expect(pkg.scripts["package:win"]).toBe("npm run build && node package.mjs");
  });

  it("@electron/packager is a pinned-exact devDependency", () => {
    expect(pkg.devDependencies["@electron/packager"]).toMatch(/^\d+\.\d+\.\d+$/);
  });
});
