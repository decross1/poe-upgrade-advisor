// @vitest-environment jsdom
/**
 * Snapshot matrix for the overlay shell (docs/specs/verdict_card.md §9;
 * issue #11 AC: "All four verdict states snapshot-tested inside the shell,
 * reusing the contracts/fixtures/ set from #25 verbatim — do not fork fixture
 * content"). Snapshots render the shell's OWN render tree (OverlayCard), with
 * the card mounted from the shared web/src/components implementation.
 *
 * Rows covered here: 1–11 (rows 9 and 11 landed with the chip re-diff
 * wiring, issue #64). Fixture schema validation lives in
 * web/test/fixtures.test.ts (single place, same fixtures).
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
  return { kind: "VERDICT", card, appliedOverrides: [], transientMessage: null };
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

describe("snapshot matrix — chip session states (§9 rows 9 and 11, issue #64)", () => {
  it("9. overridden-chip style — sidegrade_balanced with config.chill_from_setup overridden", () => {
    const { container } = render(
      <OverlayCard
        state={{
          kind: "VERDICT",
          card: sidegradeBalanced,
          appliedOverrides: [{ assumption_id: "config.chill_from_setup", value: false }],
          transientMessage: null,
        }}
      />,
    );
    expect(container.querySelector(".chip--overridden")).toBeTruthy();
    expect(container.firstChild).toMatchSnapshot();
  });

  it("11. REDIFFING — pending chip spins, whole strip disabled (§8.3, S2)", () => {
    const { container } = render(
      <OverlayCard
        state={{
          kind: "REDIFFING",
          card: sidegradeBalanced,
          appliedOverrides: [],
          pendingChipId: "config.chill_from_setup",
        }}
      />,
    );
    const strip = container.querySelector(".chip-strip")!;
    expect(strip.getAttribute("aria-busy")).toBe("true");
    expect(container.querySelector(".chip--pending .chip-spinner")).toBeTruthy();
    // Every tappable chip is a disabled button while the re-diff is in flight.
    for (const button of Array.from(strip.querySelectorAll("button"))) {
      expect(button.disabled).toBe(true);
    }
    expect(container.firstChild).toMatchSnapshot();
  });

  it("RULING-21: the transient message reuses the sentence slot (I2 element count intact)", () => {
    const { container } = render(
      <OverlayCard
        state={{
          kind: "VERDICT",
          card: sidegradeBalanced,
          appliedOverrides: [],
          transientMessage: "Couldn't recompute — tap the chip to retry.",
        }}
      />,
    );
    // ONE sentence element, and it carries the transient text instead of
    // the card's quoted sentence (the slot is reused, not duplicated).
    const sentences = container.querySelectorAll(".verdict-sentence");
    expect(sentences).toHaveLength(1);
    expect(sentences[0].textContent).toBe("Couldn't recompute — tap the chip to retry.");
    expect(sentences[0].textContent).not.toContain(sidegradeBalanced.sentence);
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
      tapChip: vi.fn(),
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
      tapChip: vi.fn(),
    };
    const { container } = render(<ShellApp />);
    expect(container.firstChild).toBeNull(); // HIDDEN
    act(() => pushState?.(verdictState(sidegradeBossing)));
    expect(container.textContent).toContain("SIDEGRADE");
    delete window.poeOverlay;
  });

  it("I3: a boolean chip tap crosses the bridge to the flow as the tapped assumption (one tap = at most one /diff, S2)", () => {
    const tapChip = vi.fn();
    let pushState: ((s: ShellState) => void) | undefined;
    window.poeOverlay = {
      onState: (cb) => {
        pushState = cb;
      },
      openDetails: vi.fn(),
      tapChip,
    };
    render(<ShellApp />);
    act(() => pushState?.(verdictState(upgradeMapping)));

    // The boolean chip is a button (RULING-14); the string chip is not.
    const eoChip = screen.getByRole("button", { name: "crit recently" });
    fireEvent.click(eoChip);
    expect(tapChip).toHaveBeenCalledTimes(1);
    expect(tapChip).toHaveBeenCalledWith(
      expect.objectContaining({ id: "config.elemental_overload", value: true }),
    );

    // REDIFFING disables the whole strip: a click during the flight reaches
    // NOBODY — not even the bridge (belt-and-suspenders with the flow's own
    // phase guard, tested in diffFlow.test.ts).
    act(() =>
      pushState?.({
        kind: "REDIFFING",
        card: upgradeMapping,
        appliedOverrides: [],
        pendingChipId: "config.elemental_overload",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "flasks up" }));
    expect(tapChip).toHaveBeenCalledTimes(1);
    delete window.poeOverlay;
  });
});
