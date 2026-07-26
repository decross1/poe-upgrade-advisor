// @vitest-environment jsdom
/**
 * Issue #11 AC: "Card renders ≤50 ms after response receipt (measured and
 * asserted in a test, not eyeballed)."
 *
 * Headless, this measures the component render+commit for every golden
 * fixture inside the shell's render tree (OverlayCard) — the part the shell
 * controls. Real-frame evidence on native stacks is the bench's job:
 * ADR-0004 measured trigger→frame p95 32.8 ms for this same shared card UI
 * under software rasterization (overlay/bench/results/). Together: the headless
 * assertion guards regressions in the render path; the bench guards the stack.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { VerdictCard as VerdictCardData } from "../../web/src/lib/verdictFormat";
import { OverlayCard } from "../src/renderer/OverlayCard";
import type { ShellState } from "../src/shellState";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";
import downgradeMappingJson from "../../contracts/fixtures/downgrade_mapping.json";
import cantEvaluateTriggerJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import edgeDegradedJson from "../../contracts/fixtures/edge_degraded_minimal.json";
import upgradeRichChipJson from "../../contracts/fixtures/upgrade_rich_assumptions_chip.json";
import sidegradeBalancedJson from "../../contracts/fixtures/sidegrade_balanced_low_confidence.json";

const RENDER_BUDGET_MS = 50;

/** Fresh-session VERDICT projection (no overrides, no transient message). */
function verdictState(card: VerdictCardData): ShellState {
  return { kind: "VERDICT", card, appliedOverrides: [], transientMessage: null };
}

const FIXTURES: Record<string, VerdictCardData> = {
  upgrade_mapping: upgradeMappingJson as VerdictCardData,
  sidegrade_bossing: sidegradeBossingJson as VerdictCardData,
  downgrade_mapping: downgradeMappingJson as VerdictCardData,
  cant_evaluate_trigger_build: cantEvaluateTriggerJson as VerdictCardData,
  edge_degraded_minimal: edgeDegradedJson as VerdictCardData,
  upgrade_rich_assumptions_chip: upgradeRichChipJson as VerdictCardData,
  sidegrade_balanced_low_confidence: sidegradeBalancedJson as VerdictCardData,
};

describe("render budget (I6 / overlay hard rule)", () => {
  it("every golden fixture renders within 50 ms of response receipt", () => {
    // Warm up module-level costs (first render pays React/jsdom one-time
    // init); the budget applies to steady-state card renders.
    render(<OverlayCard state={verdictState(FIXTURES.upgrade_mapping)} />).unmount();

    const timings: Record<string, number> = {};
    for (const [name, card] of Object.entries(FIXTURES)) {
      const t0 = performance.now();
      const view = render(<OverlayCard state={verdictState(card)} />);
      timings[name] = performance.now() - t0;
      view.unmount();
    }
    console.log("render timings (ms):", JSON.stringify(timings, null, 2));
    for (const [name, ms] of Object.entries(timings)) {
      expect(ms, `${name} rendered in ${ms.toFixed(1)} ms, over the ${RENDER_BUDGET_MS} ms budget`).toBeLessThan(
        RENDER_BUDGET_MS,
      );
    }
  });
});
