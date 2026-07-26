// @vitest-environment jsdom
/**
 * Snapshot matrix for the overlay shell (docs/specs/verdict_card.md §9;
 * issue #11 AC: "All four verdict states snapshot-tested inside the shell,
 * reusing the contracts/fixtures/ set from #25 verbatim — do not fork fixture
 * content"). Snapshots render the shell's OWN render tree (OverlayCard), with
 * the card mounted from the shared web/src/components implementation.
 *
 * Rows covered here: 1–8 and 10. Rows 9 (overridden-chip style) and 11
 * (REDIFFING) belong to TASK-204 (#12) chip re-diff wiring — not this task.
 * Fixture schema validation lives in web/test/fixtures.test.ts (single place,
 * same fixtures).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { VerdictCard as VerdictCardData } from "../../web/src/lib/verdictFormat";
import { OverlayCard } from "../src/renderer/OverlayCard";
import { ShellApp } from "../src/renderer/ShellApp";
import { LOADING_FLASH_GUARD_MS, type ShellState } from "../src/shellState";

// contracts/fixtures/ — used verbatim (read-only; contracts/ is protected).
import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";
import downgradeMappingJson from "../../contracts/fixtures/downgrade_mapping.json";
import cantEvaluateTriggerJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import edgeDegradedJson from "../../contracts/fixtures/edge_degraded_minimal.json";
import upgradeRichChipJson from "../../contracts/fixtures/upgrade_rich_assumptions_chip.json";
import sidegradeBalancedJson from "../../contracts/fixtures/sidegrade_balanced_low_confidence.json";
// Spec §9 gap case: local copy until a golden fixture lands (row 8).
import localBarOverflowJson from "./fixtures/local_bar_overflow.json";

const upgradeMapping = upgradeMappingJson as VerdictCardData;
const sidegradeBossing = sidegradeBossingJson as VerdictCardData;
const downgradeMapping = downgradeMappingJson as VerdictCardData;
const cantEvaluateTrigger = cantEvaluateTriggerJson as VerdictCardData;
const edgeDegraded = edgeDegradedJson as VerdictCardData;
const upgradeRichChip = upgradeRichChipJson as VerdictCardData;
const sidegradeBalanced = sidegradeBalancedJson as VerdictCardData;
const localBarOverflow = localBarOverflowJson as VerdictCardData;

const MINUS = "−";

function verdictState(card: VerdictCardData): ShellState {
  return { kind: "VERDICT", card };
}

describe("snapshot matrix — the four verdict states (§9 rows 1–4)", () => {
  it("1. UPGRADE — upgrade_mapping.json", () => {
    const { container } = render(<OverlayCard state={verdictState(upgradeMapping)} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("2. SIDEGRADE — sidegrade_bossing.json", () => {
    const { container } = render(<OverlayCard state={verdictState(sidegradeBossing)} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("3. DOWNGRADE — downgrade_mapping.json", () => {
    const { container } = render(<OverlayCard state={verdictState(downgradeMapping)} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("4. CAN'T EVALUATE — cant_evaluate_trigger_build.json", () => {
    const { container } = render(<OverlayCard state={verdictState(cantEvaluateTrigger)} />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe("snapshot matrix — fixture variants (§9 rows 5–8)", () => {
  it("5. CAN'T EVALUATE degraded minimal — edge_degraded_minimal.json", () => {
    const { container } = render(<OverlayCard state={verdictState(edgeDegraded)} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("6. UPGRADE + low-confidence badge + 6 chips — upgrade_rich_assumptions_chip.json", () => {
    const { container } = render(<OverlayCard state={verdictState(upgradeRichChip)} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("7. balanced-preset tolerance — sidegrade_balanced_low_confidence.json", () => {
    const { container } = render(<OverlayCard state={verdictState(sidegradeBalanced)} />);
    expect(container.firstChild).toMatchSnapshot();
  });

  it("8. bar overflow » — local_bar_overflow.json", () => {
    const { container } = render(<OverlayCard state={verdictState(localBarOverflow)} />);
    expect(container.firstChild).toMatchSnapshot();
  });
});

describe("snapshot matrix — shell UI states (§9 row 10)", () => {
  afterEach(() => vi.useRealTimers());

  it("LOADING — nothing before the 120 ms flash guard, one line after (RULING-19)", () => {
    vi.useFakeTimers();
    const { container } = render(<OverlayCard state={{ kind: "LOADING" }} />);
    expect(container.firstChild).toBeNull(); // flash guard: no flash on fast diffs
    act(() => vi.advanceTimersByTime(LOADING_FLASH_GUARD_MS + 1));
    expect(screen.getByRole("status").textContent).toBe("Evaluating…");
    expect(container.firstChild).toMatchSnapshot();
  });

  it("ERROR_NO_BUILD — exact §8.2 text + single import affordance", () => {
    const { container } = render(<OverlayCard state={{ kind: "ERROR_NO_BUILD" }} />);
    expect(screen.getByText("No build imported.")).toBeTruthy();
    expect(container.firstChild).toMatchSnapshot();
  });

  it("ERROR_UNPARSEABLE — exact §8.2 text, no affordance", () => {
    const { container } = render(<OverlayCard state={{ kind: "ERROR_UNPARSEABLE" }} />);
    expect(screen.getByText("Couldn't read that item — copy it in game with Ctrl+C.")).toBeTruthy();
    expect(container.querySelector("a")).toBeNull();
    expect(container.firstChild).toMatchSnapshot();
  });

  it("ERROR_UNAVAILABLE — exact §8.2 text, no affordance", () => {
    const { container } = render(<OverlayCard state={{ kind: "ERROR_UNAVAILABLE" }} />);
    expect(screen.getByText("Advisor engine isn't running.")).toBeTruthy();
    expect(container.querySelector("a")).toBeNull();
    expect(container.firstChild).toMatchSnapshot();
  });

  it("HIDDEN renders nothing", () => {
    const { container } = render(<OverlayCard state={{ kind: "HIDDEN" }} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("behavioral rulings the snapshots make hard to review", () => {
  it("RULING-6: CANT_EVALUATE suppresses both deltas as em-dashes and emphasizes the details affordance", () => {
    const { container } = render(<OverlayCard state={verdictState(cantEvaluateTrigger)} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("+0.0%");
    expect((text.match(/—/g) ?? []).length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector(".details-link--emphasized")).toBeTruthy();
  });

  it("RULING-4: mixed signs stay mixed — DOWNGRADE keeps a positive defense number", () => {
    const { container } = render(<OverlayCard state={verdictState(downgradeMapping)} />);
    const text = container.textContent ?? "";
    expect(text).toContain(`${MINUS}18.2%`);
    expect(text).toContain("+3.1%");
  });

  it("I7: the details affordance deep-links /breakdown/{diff_id} through the bridge, never in-window", () => {
    const openDetails = vi.fn();
    let pushState: ((s: ShellState) => void) | undefined;
    window.poeOverlay = {
      onState: (cb) => {
        pushState = cb;
      },
      openDetails,
    };
    render(<ShellApp />);
    act(() => pushState?.(verdictState(upgradeMapping)));
    const link = screen.getByText("Open details ▸");
    fireEvent.click(link);
    expect(openDetails).toHaveBeenCalledWith(`/breakdown/${upgradeMapping.diff_id}`);
    delete window.poeOverlay;
  });

  it("ShellApp paints states pushed over the bridge (HIDDEN → VERDICT)", () => {
    let pushState: ((s: ShellState) => void) | undefined;
    window.poeOverlay = {
      onState: (cb) => {
        pushState = cb;
      },
      openDetails: vi.fn(),
    };
    const { container } = render(<ShellApp />);
    expect(container.firstChild).toBeNull(); // HIDDEN
    act(() => pushState?.(verdictState(sidegradeBossing)));
    expect(container.textContent).toContain("SIDEGRADE");
    delete window.poeOverlay;
  });
});
