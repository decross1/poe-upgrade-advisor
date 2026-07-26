/**
 * TASK-301 (issue #13) — every FE-local breakdown fixture MUST validate
 * against the Breakdown shape in contracts/openapi.yaml and tell the same
 * story as the golden verdict fixture of the same name (matching diff_id;
 * empty drivers exactly when the verdict is CANT_EVALUATE). Same discipline
 * as fixtures.test.ts / buildImportFixture.test.ts: conformance is a test.
 *
 * Fixtures live in web/mock/fixtures/breakdown/ (NOT contracts/fixtures/)
 * because contracts/ is a protected path and issue #13 carries no
 * protected-change label — see web/mock/fixtures/README.md.
 */
import Ajv2020 from "ajv/dist/2020";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import YAML from "yaml";
import { describe, expect, it } from "vitest";

const CONTRACTS_DIR = join(import.meta.dirname, "..", "..", "contracts");
const VERDICT_FIXTURES_DIR = join(CONTRACTS_DIR, "fixtures");
const BREAKDOWN_FIXTURES_DIR = join(import.meta.dirname, "..", "mock", "fixtures", "breakdown");

const openapi = YAML.parse(readFileSync(join(CONTRACTS_DIR, "openapi.yaml"), "utf8"));
const breakdownSchema = {
  $id: "https://poe-upgrade-advisor/openapi-breakdown",
  ...openapi.components.schemas.Breakdown,
  components: openapi.components,
};
const ajv = new Ajv2020({ strict: false, allErrors: true });
const validate = ajv.compile(breakdownSchema);

function readJson(dir: string, name: string) {
  return JSON.parse(readFileSync(join(dir, `${name}.json`), "utf8"));
}

const verdictNames = readdirSync(VERDICT_FIXTURES_DIR)
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.slice(0, -".json".length));
const breakdownNames = readdirSync(BREAKDOWN_FIXTURES_DIR)
  .filter((f) => f.endsWith(".json"))
  .map((f) => f.slice(0, -".json".length));

describe("breakdown fixtures (web/mock/fixtures/breakdown/)", () => {
  it("cover every golden verdict fixture, one for one", () => {
    expect([...breakdownNames].sort()).toEqual([...verdictNames].sort());
  });

  for (const name of breakdownNames) {
    it(`${name}: validates against openapi's Breakdown shape`, () => {
      const data = readJson(BREAKDOWN_FIXTURES_DIR, name);
      expect(validate(data), ajv.errorsText(validate.errors)).toBe(true);
    });

    it(`${name}: is consistent with its verdict fixture (diff_id, drivers vs verdict)`, () => {
      const breakdown = readJson(BREAKDOWN_FIXTURES_DIR, name);
      const verdict = readJson(VERDICT_FIXTURES_DIR, name);
      expect(breakdown.diff_id).toBe(verdict.diff_id);
      if (verdict.verdict === "CANT_EVALUATE") {
        expect(breakdown.drivers).toEqual([]); // I5: no drivers when no delta was computed
      } else {
        expect(breakdown.drivers.length).toBeGreaterThan(0);
      }
    });
  }
});
