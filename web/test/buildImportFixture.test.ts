/**
 * TASK-207 (issue #29) — the FE-local build-summary fixture MUST validate
 * against the BuildSummary shape in contracts/openapi.yaml (the mock serves
 * it as a /build response; the success snapshot renders it). Same discipline
 * as fixtures.test.ts: conformance is a test, not a convention.
 *
 * The fixture lives in web/mock/fixtures/ (NOT contracts/fixtures/) because
 * contracts/ is a protected path and issue #29 carries no protected-change
 * label — see web/mock/fixtures/README.md for the promotion path.
 */
import Ajv2020 from "ajv/dist/2020";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import YAML from "yaml";
import { describe, expect, it } from "vitest";

const CONTRACTS_DIR = join(import.meta.dirname, "..", "..", "contracts");
const FIXTURE = join(import.meta.dirname, "..", "mock", "fixtures", "build_summary.json");

const openapi = YAML.parse(readFileSync(join(CONTRACTS_DIR, "openapi.yaml"), "utf8"));

// Wrap BuildSummary with the components bag so any internal $ref resolves —
// same pattern as fixtures.test.ts. Lenient ajv: the `components` bag is an
// OpenAPI keyword ajv's strict mode rejects.
const buildSummarySchema = {
  $id: "https://poe-upgrade-advisor/openapi-build-summary",
  ...openapi.components.schemas.BuildSummary,
  components: openapi.components,
};
const ajv = new Ajv2020({ strict: false, allErrors: true });
const validate = ajv.compile(buildSummarySchema);

describe("build-summary fixture (web/mock/fixtures/build_summary.json)", () => {
  it("validates against openapi's BuildSummary shape", () => {
    const data = JSON.parse(readFileSync(FIXTURE, "utf8"));
    expect(validate(data), ajv.errorsText(validate.errors)).toBe(true);
  });

  it("is consistent with the golden verdict fixtures (same league-start build)", () => {
    // The verdict fixtures' chips reference a Vortex build on mapping; the
    // import fixture must tell the same story or the harness contradicts itself.
    const data = JSON.parse(readFileSync(FIXTURE, "utf8"));
    const upgradeMapping = JSON.parse(
      readFileSync(join(CONTRACTS_DIR, "fixtures", "upgrade_mapping.json"), "utf8"),
    );
    expect(data.main_skill.name).toBe("Vortex");
    expect(data.preset_default).toBe(upgradeMapping.preset);
  });
});
