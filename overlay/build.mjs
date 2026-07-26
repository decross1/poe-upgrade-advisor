#!/usr/bin/env node
/**
 * Build the shell into dist/:
 *   dist/main.cjs      — Electron main (node platform, electron external)
 *   dist/preload.cjs   — preload bridge (sandboxed, cjs)
 *   dist/renderer.js   — card UI bundle (browser platform)
 *   dist/renderer.css  — extracted shared styles
 *   dist/index.html    — window page
 *
 * Cross-package imports into web/src (shared card component, generated
 * client) are bundled, so dist/ is self-contained.
 */
import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(HERE, "dist");

await mkdir(DIST, { recursive: true });

await build({
  entryPoints: [path.join(HERE, "src/main.ts"), path.join(HERE, "src/preload.ts")],
  outdir: DIST,
  outExtension: { ".js": ".cjs" },
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["electron"],
  target: "node22",
  sourcemap: true,
  // web/src imports resolve bare deps (none today, but the generated client
  // may gain some) from THIS package's node_modules regardless of importer.
  nodePaths: [path.join(HERE, "node_modules")],
});

await build({
  entryPoints: [path.join(HERE, "src/renderer/renderer.tsx")],
  outdir: DIST,
  bundle: true,
  platform: "browser",
  format: "iife",
  jsx: "automatic",
  target: "chrome130",
  sourcemap: true,
  nodePaths: [path.join(HERE, "node_modules")], // react/react-dom for web/src/components
});

await copyFile(path.join(HERE, "src/renderer/index.html"), path.join(DIST, "index.html"));

console.log("overlay: built dist/{main.cjs,preload.cjs,renderer.js,renderer.css,index.html}");
