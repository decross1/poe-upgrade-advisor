/// <reference types="vitest/config" />
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const HERE = path.dirname(fileURLToPath(import.meta.url));

// Cross-package sharing: the card component and generated client are imported
// from ../web/src, which has no node_modules of its own — pin bare react
// imports to THIS package's copies so resolution never depends on CWD.
export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: {
    alias: [
      { find: "react", replacement: path.join(HERE, "node_modules/react") },
      { find: "react-dom", replacement: path.join(HERE, "node_modules/react-dom") },
    ],
    dedupe: ["react", "react-dom"],
  },
  test: {
    // Default node environment; tsx tests opt into jsdom per-file.
    include: ["test/**/*.test.{ts,tsx}"],
    setupFiles: ["test/setup.ts"],
  },
});
