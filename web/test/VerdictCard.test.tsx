/**
 * Snapshot matrix (docs/specs/verdict_card.md §9) + behavioral assertions for
 * the rulings that snapshots alone make hard to review. Every row of the
 * matrix that concerns the card itself exists here; LOADING/ERROR/REDIFFING
 * are overlay UI states tied to HTTP wiring (TASK-206) and re-diff UX
 * (TASK-204) and are deliberately out of scope for TASK-205.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VerdictCard } from "../src/components/VerdictCard";
import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";
import downgradeMappingJson from "../../contracts/fixtures/downgrade_mapping.json";
import cantEvaluateTriggerJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import upgradeRichChipJson from "../../contracts/fixtures/upgrade_rich_assumptions_chip.json";
import sidegradeBalancedJson from "../../contracts/fixtures/sidegrade_balanced_low_confidence.json";
import edgeDegradedJson from "../../contracts/fixtures/edge_degraded_minimal.json";
import localBarOverflowJson from "./fixtures/local_bar_overflow.json";

// JSON imports widen to string/boolean; fixtures.test.ts proves these files
// satisfy both contract schemas, so bind them to the generated types here.
const upgradeMapping = upgradeMappingJson as VerdictCardData;
const sidegradeBossing = sidegradeBossingJson as VerdictCardData;
const downgradeMapping = downgradeMappingJson as VerdictCardData;
const cantEvaluateTrigger = cantEvaluateTriggerJson as VerdictCardData;
const upgradeRichChip = upgradeRichChipJson as VerdictCardData;
const sidegradeBalanced = sidegradeBalancedJson as VerdictCardData;
const edgeDegraded = edgeDegradedJson as VerdictCardData;
const localBarOverflow = localBarOverflowJson as VerdictCardData;

const MINUS = "−";

describe("snapshot matrix (§9)", () => {
  it("1. UPGRADE — upgrade_mapping.json", () => {
    const { container } = render(<VerdictCard card={upgradeMapping} />);
    expect(container).toMatchSnapshot();
  });

  it("2. SIDEGRADE — sidegrade_bossing.json", () => {
    const { container } = render(<VerdictCard card={sidegradeBossing} />);
    expect(container).toMatchSnapshot();
  });

  it("3. DOWNGRADE — downgrade_mapping.json", () => {
    const { container } = render(<VerdictCard card={downgradeMapping} />);
    expect(container).toMatchSnapshot();
  });

  it("4. CAN'T EVALUATE — cant_evaluate_trigger_build.json", () => {
    const { container } = render(<VerdictCard card={cantEvaluateTrigger} />);
    expect(container).toMatchSnapshot();
  });

  it("5. CAN'T EVALUATE degraded minimal — edge_degraded_minimal.json", () => {
    const { container } = render(<VerdictCard card={edgeDegraded} />);
    expect(container).toMatchSnapshot();
  });

  it("6. UPGRADE + low-confidence badge + 6 chips — upgrade_rich_assumptions_chip.json", () => {
    const { container } = render(<VerdictCard card={upgradeRichChip} />);
    expect(container).toMatchSnapshot();
  });

  it("7. balanced-preset tolerance — sidegrade_balanced_low_confidence.json", () => {
    const { container } = render(<VerdictCard card={sidegradeBalanced} />);
    expect(container).toMatchSnapshot();
  });

  it("8. bar overflow + near-zero + 40-char label — local fixture", () => {
    const { container } = render(<VerdictCard card={localBarOverflow} />);
    expect(container).toMatchSnapshot();
  });

  it("9. overridden-chip style — appliedOverrides contains config.chill_from_setup", () => {
    const applied = new Map<string, unknown>([["config.chill_from_setup", false]]);
    const { container } = render(<VerdictCard card={sidegradeBalanced} appliedOverrides={applied} />);
    expect(container).toMatchSnapshot();
  });
});

describe("CANT_EVALUATE treatment (§3.4, RULING-3/6)", () => {
  it("renders CAN'T EVALUATE with apostrophe and suppresses both deltas as em-dashes", () => {
    const { container } = render(<VerdictCard card={cantEvaluateTrigger} />);
    expect(screen.getByText("CAN'T EVALUATE")).toBeTruthy();
    expect(container.querySelectorAll(".delta-row--suppressed")).toHaveLength(2);
    // Sentinel 0s must NOT surface as numbers (fixtures README convention 2).
    expect(screen.queryByText("0.0%")).toBeNull();
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("renders the sentence field verbatim and NEVER cant_evaluate_reasons on the card", () => {
    render(<VerdictCard card={cantEvaluateTrigger} />);
    expect(screen.getByText(`"${cantEvaluateTrigger.sentence}"`)).toBeTruthy();
    for (const reason of cantEvaluateTrigger.cant_evaluate_reasons ?? []) {
      expect(screen.queryByText(reason)).toBeNull();
    }
  });

  it("emphasizes the details affordance (I5) without adding a sixth element", () => {
    const { container } = render(<VerdictCard card={cantEvaluateTrigger} />);
    const link = container.querySelector(".details-link");
    expect(link?.classList.contains("details-link--emphasized")).toBe(true);
    expect(link?.getAttribute("href")).toBe("/breakdown/d-6efc9d24");
  });

  it("degraded minimal: empty chip strip, absent reasons, 140-char sentence render intact", () => {
    const { container } = render(<VerdictCard card={edgeDegraded} />);
    expect(edgeDegraded.sentence).toHaveLength(140);
    expect(screen.getByText(`"${edgeDegraded.sentence}"`)).toBeTruthy();
    expect(container.querySelectorAll(".chip")).toHaveLength(0);
    expect(container.querySelector(".chip-strip")).not.toBeNull(); // element present, empty
  });
});

describe("low-confidence badge (§4, RULING-2/7/8)", () => {
  it("shows for confidence in [0.55, 0.75), never a numeric confidence", () => {
    const { unmount } = render(<VerdictCard card={upgradeRichChip} />);
    expect(upgradeRichChip.confidence).toBe(0.7);
    expect(screen.getByText("◦ low confidence")).toBeTruthy();
    expect(screen.queryByText("0.7")).toBeNull();
    unmount();

    render(<VerdictCard card={sidegradeBalanced} />);
    expect(screen.getByText("◦ low confidence")).toBeTruthy();
  });

  it("stays off at/above 0.75 and in CANT_EVALUATE", () => {
    const { unmount } = render(<VerdictCard card={upgradeMapping} />);
    expect(upgradeMapping.confidence).toBe(0.8);
    expect(screen.queryByText(/low confidence/)).toBeNull();
    unmount();

    render(<VerdictCard card={cantEvaluateTrigger} />);
    expect(screen.queryByText(/low confidence/)).toBeNull();
  });
});

describe("I2 bans and contract hygiene", () => {
  it("never renders preset, diff_id, compute_ms, confidence, or Assumption.value (RULING-1/2/13)", () => {
    render(<VerdictCard card={upgradeMapping} />);
    expect(screen.queryByText(/mapping/i)).toBeNull();
    expect(screen.queryByText(/d-8f2c41a7/)).toBeNull();
    expect(screen.queryByText(/142/)).toBeNull();
    expect(screen.queryByText(/0\.8/)).toBeNull();
    // Boolean values must not leak onto chips.
    expect(screen.queryByText("true")).toBeNull();
  });

  it("renders the server verdict verbatim — no spin, no second-guessing (RULING-4)", () => {
    // DOWNGRADE with positive defense delta must stay DOWNGRADE.
    render(<VerdictCard card={downgradeMapping} />);
    expect(screen.getByText("DOWNGRADE")).toBeTruthy();
    expect(screen.getByText(`${MINUS}18.2%`)).toBeTruthy();
    expect(screen.getByText("+3.1%")).toBeTruthy();
  });

  it("tolerates the reserved 'balanced' preset without rendering it (RULING-22)", () => {
    render(<VerdictCard card={sidegradeBalanced} />);
    expect(screen.queryByText(/balanced/i)).toBeNull();
    expect(screen.getByText("SIDEGRADE")).toBeTruthy();
  });
});

describe("delta bar edge cases (RULING-9/10)", () => {
  it("overflow: full bar plus » chevron, exact number", () => {
    const { container } = render(<VerdictCard card={localBarOverflow} />);
    expect(screen.getByText("+312.0%")).toBeTruthy();
    expect(container.querySelector(".delta-overflow")?.textContent).toBe("»");
    // 0.04 pp defense → near-zero: unsigned, neutral, no chevron on that row.
    expect(screen.getByText("0.0%")).toBeTruthy();
    expect(container.querySelectorAll(".delta-overflow")).toHaveLength(1);
  });
});
