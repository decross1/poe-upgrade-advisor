/**
 * Issue #79 / TASK-210-S5: measure the last unmeasured capture→card segment —
 * the shell's own overhead. The clock starts at the pollNow() that first
 * observes new item text and stops when the VERDICT ShellState reaches
 * onState; in between runs the REAL createClipboardPipeline composition
 * (watcher header detection → diff flow session machine → state projection),
 * with only the clipboard source and postDiff stubbed (immediate resolve, no
 * network). Budget: 20 ms per capture.
 *
 * Deliberately NOT in this number (see
 * overlay/bench/results/2026-08-03-capture-to-card-budget.md):
 * - the CLIPBOARD_POLL_MS=100 detection lag (pollNow is invoked at the moment
 *   the text appears, so the 0–100 ms polling wait is excluded by design);
 * - the server /diff call (postDiff resolves a golden fixture immediately);
 * - render+commit and trigger→frame, asserted by renderBudget.test.tsx and
 *   benched per ADR-0004 respectively.
 */
import { describe, expect, it, vi } from "vitest";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";
import { createClipboardPipeline, type ClipboardPipeline } from "../src/clipboardPipeline";
import type { PostDiff } from "../src/diffRequest";
import type { ShellState } from "../src/shellState";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";
import downgradeMappingJson from "../../contracts/fixtures/downgrade_mapping.json";
import cantEvaluateTriggerJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import edgeDegradedJson from "../../contracts/fixtures/edge_degraded_minimal.json";
import upgradeRichChipJson from "../../contracts/fixtures/upgrade_rich_assumptions_chip.json";
import sidegradeBalancedJson from "../../contracts/fixtures/sidegrade_balanced_low_confidence.json";

const SHELL_OVERHEAD_BUDGET_MS = 20;

const ITEM_TEXT =
  "Item Class: Wands\r\nRarity: Rare\r\nDoom Branch\r\nProphecy Wand\r\n--------\r\n";

const FIXTURES: Record<string, VerdictCard> = {
  upgrade_mapping: upgradeMappingJson as VerdictCard,
  sidegrade_bossing: sidegradeBossingJson as VerdictCard,
  downgrade_mapping: downgradeMappingJson as VerdictCard,
  cant_evaluate_trigger_build: cantEvaluateTriggerJson as VerdictCard,
  edge_degraded_minimal: edgeDegradedJson as VerdictCard,
  upgrade_rich_assumptions_chip: upgradeRichChipJson as VerdictCard,
  sidegrade_balanced_low_confidence: sidegradeBalancedJson as VerdictCard,
};

function resolvedCard(card: VerdictCard): ReturnType<PostDiff> {
  const response = Promise.resolve(card) as unknown as ReturnType<PostDiff>;
  response.cancel = vi.fn();
  return response;
}

/**
 * One capture through the real pipeline with a stub clipboard and an
 * immediately-resolving postDiff. Returns ms from the observing pollNow() to
 * the VERDICT state arriving at onState.
 */
async function measureCapture(card: VerdictCard): Promise<number> {
  const clipboard = { text: "initial non-item", readText: () => clipboard.text };
  let verdictAt: number | undefined;
  const states: ShellState[] = [];
  const pipeline: ClipboardPipeline = createClipboardPipeline({
    clipboard,
    postDiff: vi.fn((_body) => resolvedCard(card)) as unknown as PostDiff,
    onState: (state) => {
      states.push(state);
      if (state.kind === "VERDICT" && verdictAt === undefined) {
        verdictAt = performance.now();
      }
    },
    pollMs: 60_000, // interval never fires within the test; pollNow drives
  });
  try {
    pipeline.start(); // baselines the current clipboard contents
    clipboard.text = ITEM_TEXT;

    const t0 = performance.now();
    await pipeline.pollNow();
    const elapsed = (verdictAt ?? performance.now()) - t0;

    expect(states.map((s) => s.kind)).toEqual(["LOADING", "VERDICT"]);
    const verdict = states.at(-1);
    expect(verdict?.kind === "VERDICT" && verdict.card).toBe(card);
    return elapsed;
  } finally {
    pipeline.stop();
  }
}

describe("capture latency (I6 / issue #79): clipboard sample → VERDICT ShellState", () => {
  it("every golden fixture's shell overhead stays within 20 ms per capture", async () => {
    // Warm up one-time module costs (first pipeline run pays imports/init);
    // the budget applies to steady-state captures.
    await measureCapture(FIXTURES.upgrade_mapping);

    const timings: Record<string, number> = {};
    for (const [name, card] of Object.entries(FIXTURES)) {
      timings[name] = await measureCapture(card);
    }
    console.log("capture→VERDICT shell overhead (ms):", JSON.stringify(timings, null, 2));
    for (const [name, ms] of Object.entries(timings)) {
      expect(
        ms,
        `${name} shell overhead was ${ms.toFixed(2)} ms, over the ${SHELL_OVERHEAD_BUDGET_MS} ms budget`,
      ).toBeLessThan(SHELL_OVERHEAD_BUDGET_MS);
    }
  });
});
