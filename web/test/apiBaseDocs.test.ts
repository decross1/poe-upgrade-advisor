/**
 * Review regression for issue #60's README acceptance criterion.
 *
 * The one-line API target switch is user-facing setup, and the browser CORS
 * limitation changes whether that setup works during Vite development. Keep
 * both facts in web/README.md rather than only in implementation comments.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const README = readFileSync(join(import.meta.dirname, "..", "README.md"), "utf8");

describe("TASK-202 API-base documentation (issue #60)", () => {
  it("documents how to switch the web app to the real server skeleton", () => {
    expect(README).toContain("VITE_API_BASE_URL");
    expect(README).toContain("python3 -m server");
  });

  it("documents the development-browser CORS caveat and packaged behavior", () => {
    expect(README).toMatch(/\bCORS\b/i);
    expect(README).toMatch(/\bbrowser\b/i);
    expect(README).toMatch(/\bsame-origin\b/i);
  });
});
