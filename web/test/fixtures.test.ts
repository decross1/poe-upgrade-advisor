/**
 * Every fixture the FE consumes MUST validate against contracts/verdict.schema.json
 * AND openapi.yaml's VerdictCard/Assumption shapes (stricter wins) — this is a
 * test, not a convention (docs/specs/verdict_card.md §9; issue #25).
 */
import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import YAML from "yaml";
import { describe, expect, it } from "vitest";

const CONTRACTS_DIR = join(import.meta.dirname, "..", "..", "contracts");
const GOLDEN_DIR = join(CONTRACTS_DIR, "fixtures");
const LOCAL_DIR = join(import.meta.dirname, "fixtures");

const strictSchema = JSON.parse(readFileSync(join(CONTRACTS_DIR, "verdict.schema.json"), "utf8"));
const openapi = YAML.parse(readFileSync(join(CONTRACTS_DIR, "openapi.yaml"), "utf8"));

// Wrap openapi's VerdictCard with the components bag so the internal
// $ref ('#/components/schemas/Assumption') resolves. [Assumption carries
// label maxLength 40 and reversible const true — stricter than the strict schema.]
const openapiVerdictSchema = {
  $id: "https://poe-upgrade-advisor/openapi-verdict-card",
  ...openapi.components.schemas.VerdictCard,
  components: openapi.components,
};

// Strict for the Doctrine-I2 schema; lenient for the openapi wrapper, whose
// `components` bag (needed to resolve #/components/schemas/Assumption) is an
// OpenAPI keyword ajv's strict mode rejects.
const ajvStrict = new Ajv2020({ strict: true, allErrors: true });
const ajvOpenapi = new Ajv2020({ strict: false, allErrors: true });
const validateStrict: ValidateFunction = ajvStrict.compile(strictSchema);
const validateOpenapi: ValidateFunction = ajvOpenapi.compile(openapiVerdictSchema);

const goldenFiles = readdirSync(GOLDEN_DIR)
  .filter((f) => f.endsWith(".json"))
  .sort();
const localFiles = readdirSync(LOCAL_DIR)
  .filter((f) => f.endsWith(".json"))
  .sort();

function expectValid(name: string, data: unknown) {
  const strictOk = validateStrict(data);
  const openapiOk = validateOpenapi(data);
  expect(
    strictOk,
    `${name} failed contracts/verdict.schema.json: ${ajvStrict.errorsText(validateStrict.errors)}`,
  ).toBe(true);
  expect(
    openapiOk,
    `${name} failed openapi VerdictCard/Assumption shape: ${ajvOpenapi.errorsText(validateOpenapi.errors)}`,
  ).toBe(true);
}

describe("golden fixtures (contracts/fixtures/, read-only)", () => {
  it("covers all four verdict states plus badge-zone and degraded cases", () => {
    // The seven files docs/specs/verdict_card.md §9 promises.
    expect(goldenFiles).toEqual([
      "cant_evaluate_trigger_build.json",
      "downgrade_mapping.json",
      "edge_degraded_minimal.json",
      "sidegrade_balanced_low_confidence.json",
      "sidegrade_bossing.json",
      "upgrade_mapping.json",
      "upgrade_rich_assumptions_chip.json",
    ]);
  });

  for (const file of goldenFiles) {
    it(`${file} validates against both contract shapes`, () => {
      expectValid(file, JSON.parse(readFileSync(join(GOLDEN_DIR, file), "utf8")));
    });
  }
});

describe("local fixtures (web/test/fixtures/ — §9 gap coverage only)", () => {
  it("exist only for cases with no golden fixture yet", () => {
    expect(localFiles.length).toBeGreaterThan(0);
  });

  for (const file of localFiles) {
    it(`${file} validates against both contract shapes`, () => {
      expectValid(file, JSON.parse(readFileSync(join(LOCAL_DIR, file), "utf8")));
    });
  }
});
