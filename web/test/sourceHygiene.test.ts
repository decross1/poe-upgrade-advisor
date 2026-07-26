/**
 * Source hygiene gates for web/src, as plain repo tests (PM-REFINEMENT (3) on
 * #25: scripts/check_invariants.py scans overlay/src only and is protected —
 * enforce the Doctrine-I1 banned-filename rule for web/src HERE instead).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC_DIR = join(import.meta.dirname, "..", "src");
const SRC_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".rs", ".vue", ".svelte"]);

// Mirror of scripts/check_invariants.py (I1). Do not weaken one without the other.
const BANNED_FILENAME_SUBSTRINGS = ["settings", "preferences", "configpanel", "optionsmenu"];

// Components must stay portable into the overlay shell: no engine/server
// imports, no network calls in source (fixtures only; wiring is TASK-206).
const FORBIDDEN_IMPORT = /from\s+["'][^"']*(\.\.\/)*(engine|server)\//;
const NETWORK_CALL = [/\bfetch\s*\(/, /XMLHttpRequest/, /\baxios\b/, /new\s+WebSocket/];

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* walk(full);
    else yield full;
  }
}

const sourceFiles = [...walk(SRC_DIR)].filter((f) =>
  SRC_EXTENSIONS.has(f.slice(f.lastIndexOf("."))),
);

describe("Doctrine I1 — no settings surface (banned filenames, plain-test version)", () => {
  it("web/src exists and has source files", () => {
    expect(sourceFiles.length).toBeGreaterThan(0);
  });

  it("no source filename contains a settings-like substring", () => {
    const offenders = sourceFiles.filter((f) => {
      const name = f.slice(f.lastIndexOf("/") + 1).toLowerCase();
      return BANNED_FILENAME_SUBSTRINGS.some((b) => name.includes(b));
    });
    expect(offenders.map((f) => relative(SRC_DIR, f))).toEqual([]);
  });
});

describe("portability contract (issue #25: zero engine/server imports, zero network)", () => {
  it("no source file imports from engine/ or server/", () => {
    const offenders = sourceFiles.filter((f) => FORBIDDEN_IMPORT.test(readFileSync(f, "utf8")));
    expect(offenders.map((f) => relative(SRC_DIR, f))).toEqual([]);
  });

  it("no source file makes network calls", () => {
    const offenders = sourceFiles.filter((f) => {
      const text = readFileSync(f, "utf8");
      return NETWORK_CALL.some((pattern) => pattern.test(text));
    });
    expect(offenders.map((f) => relative(SRC_DIR, f))).toEqual([]);
  });
});
