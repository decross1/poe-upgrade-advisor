#!/usr/bin/env node
/**
 * Package the overlay as a runnable Windows x86-64 Electron app (TASK-215-S1).
 *
 * The target machine is a PLAYER's: no npm, no Electron, no compiler. The
 * esbuild bundles in dist/ are self-contained (react/react-dom and web/src
 * are bundled in), so the packaged app is dist/ + package.json and nothing
 * else — no node_modules ship.
 *
 * ARTIFACT CONTRACT: OUT_DIR / APP_NAME / PACKAGED_EXE_PATH are hardcoded by
 * packaging/launch.py (TASK-215-S2) and scripts/package_mvp_windows.ps1
 * (TASK-215-S3). Renaming them silently breaks the player's launch; the
 * values are pinned in test/packageWindows.test.ts.
 *
 * Importing this module is side-effect free: the packager only runs when the
 * file is executed directly (`node package.mjs`, via `npm run package:win`).
 */
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

// --- Artifact contract (cross-stage, do not rename) ---
export const OUT_DIR = "dist-win";
export const APP_NAME = "PoEUpgradeAdvisorOverlay";
export const PLATFORM = "win32";
export const ARCH = "x64";
export const PACKAGED_APP_DIR = `${APP_NAME}-${PLATFORM}-${ARCH}`;
export const PACKAGED_EXE_PATH = path.posix.join(OUT_DIR, PACKAGED_APP_DIR, `${APP_NAME}.exe`);

/**
 * Packager ignore rule: keep only what the app needs at runtime (dist/ and
 * package.json), drop everything else (src/, test/, bench/, node_modules,
 * toolchain configs, and any previous package run under dist-win/).
 * The packager passes paths relative to `dir` with a leading slash.
 */
export function shouldIgnore(filePath) {
  const rel = filePath.replace(/\\/g, "/").replace(/^\//, "");
  if (rel === "") return false; // the app root itself
  if (rel === "package.json") return false;
  if (rel === "dist" || rel.startsWith("dist/")) return false;
  return true;
}

/**
 * Resolved @electron/packager options. Deliberately NO icon and NO
 * win32metadata: those invoke rcedit, which needs wine when packaging from
 * Linux and buys nothing for a test build.
 */
export function packagerOptions() {
  return {
    dir: HERE,
    out: path.join(HERE, OUT_DIR),
    name: APP_NAME,
    platform: PLATFORM,
    arch: ARCH,
    asar: true,
    overwrite: true,
    ignore: shouldIgnore,
  };
}

const isDirectRun =
  process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;

if (isDirectRun) {
  const { packager } = await import("@electron/packager");
  console.log(`overlay: packaging ${APP_NAME} for ${PLATFORM}-${ARCH} (downloads Electron once)...`);
  const appPaths = await packager(packagerOptions());
  for (const appPath of appPaths) {
    console.log(`overlay: packaged ${path.relative(HERE, appPath)}`);
  }
  console.log(`overlay: artifact ${PACKAGED_EXE_PATH}`);
}
