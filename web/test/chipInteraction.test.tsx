/**
 * Assumptions chip — Doctrine I3's one-tap reversal, MVP scope (RULING-14/15,
 * PM-REFINEMENT on #25): tappability is by VALUE TYPE. Payload emission only;
 * HTTP wiring is TASK-206, full re-diff UX is TASK-204.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VerdictCard } from "../src/components/VerdictCard";
import type { OverrideEntry } from "../src/lib/overrides";

import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBossingJson from "../../contracts/fixtures/sidegrade_bossing.json";
import cantEvaluateTriggerJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import upgradeRichChipJson from "../../contracts/fixtures/upgrade_rich_assumptions_chip.json";

// JSON imports widen to string/boolean; fixtures.test.ts proves schema
// conformance, so bind to the generated types here.
const upgradeMapping = upgradeMappingJson as VerdictCardData;
const sidegradeBossing = sidegradeBossingJson as VerdictCardData;
const cantEvaluateTrigger = cantEvaluateTriggerJson as VerdictCardData;
const upgradeRichChip = upgradeRichChipJson as VerdictCardData;

function chipLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".chip")].map((c) => c.textContent ?? "");
}

describe("rendering (RULING-11/12/13)", () => {
  it("renders chips verbatim in server order — no sorting or filtering", () => {
    const { container } = render(<VerdictCard card={upgradeRichChip} />);
    expect(chipLabels(container)).toEqual(upgradeRichChip.assumptions.map((a) => a.label));
  });

  it("dims impactful:false chips but keeps them visible and tappable (fixtures README conv. 6)", () => {
    const { container } = render(<VerdictCard card={upgradeMapping} />);
    const flasksUp = screen.getByText("flasks up");
    expect(flasksUp.classList.contains("chip--dimmed")).toBe(true);
    expect(flasksUp.tagName).toBe("BUTTON"); // still flippable despite dimming
    expect(container.querySelectorAll(".chip")).toHaveLength(3);
  });
});

describe("tappability by value type (RULING-14/15)", () => {
  it("boolean chips are buttons; string-valued chips are display-only spans", () => {
    render(<VerdictCard card={upgradeMapping} />);
    expect(screen.getByText("crit recently").tagName).toBe("BUTTON");
    expect(screen.getByText("skill: Vortex").tagName).toBe("SPAN");
    // Display-only means no press affordance at all.
    expect(screen.getByText("skill: Vortex").closest("button")).toBeNull();
  });

  it("a tap on a boolean chip emits exactly [{assumption_id, value: !value}] (RULING-16)", () => {
    const onOverride = vi.fn<(p: OverrideEntry[]) => void>();
    render(<VerdictCard card={upgradeMapping} onOverride={onOverride} />);
    fireEvent.click(screen.getByText("crit recently"));
    expect(onOverride).toHaveBeenCalledTimes(1);
    expect(onOverride).toHaveBeenCalledWith([{ assumption_id: "config.elemental_overload", value: false }]);
  });

  it("dimmed (impactful:false) boolean chips flip too — PM-REFINEMENT (2)", () => {
    const onOverride = vi.fn<(p: OverrideEntry[]) => void>();
    render(<VerdictCard card={upgradeMapping} onOverride={onOverride} />);
    fireEvent.click(screen.getByText("flasks up"));
    expect(onOverride).toHaveBeenCalledWith([{ assumption_id: "config.flasks_up", value: false }]);
  });

  it("tapping a non-boolean chip emits nothing (skill chips are display-only in MVP)", () => {
    const onOverride = vi.fn<(p: OverrideEntry[]) => void>();
    render(<VerdictCard card={sidegradeBossing} onOverride={onOverride} />);
    fireEvent.click(screen.getByText("skill: Boneshatter (yours)"));
    expect(onOverride).not.toHaveBeenCalled();
  });

  it("the CANT_EVALUATE 'trigger build' chip is boolean and flippable (§3.4/§6.2)", () => {
    const onOverride = vi.fn<(p: OverrideEntry[]) => void>();
    render(<VerdictCard card={cantEvaluateTrigger} onOverride={onOverride} />);
    fireEvent.click(screen.getByText("trigger build"));
    expect(onOverride).toHaveBeenCalledWith([{ assumption_id: "main_skill.trigger_ambiguity", value: false }]);
    // ...while its best-guess skill chip stays display-only.
    expect(screen.getByText("skill: Cremation").tagName).toBe("SPAN");
  });
});

describe("session override accumulation (RULING-17)", () => {
  it("emits the FULL accumulated overrides array, not just the tapped chip", () => {
    const onOverride = vi.fn<(p: OverrideEntry[]) => void>();
    const applied = new Map<string, unknown>([["config.elemental_overload", false]]);
    render(<VerdictCard card={upgradeMapping} appliedOverrides={applied} onOverride={onOverride} />);
    fireEvent.click(screen.getByText("flasks up"));
    expect(onOverride).toHaveBeenCalledWith([
      { assumption_id: "config.elemental_overload", value: false },
      { assumption_id: "config.flasks_up", value: false },
    ]);
  });

  it("tapping an overridden chip REMOVES the override (tap again to restore, §7.1)", () => {
    const onOverride = vi.fn<(p: OverrideEntry[]) => void>();
    const applied = new Map<string, unknown>([
      ["config.elemental_overload", false],
      ["config.flasks_up", false],
    ]);
    render(<VerdictCard card={upgradeMapping} appliedOverrides={applied} onOverride={onOverride} />);
    fireEvent.click(screen.getByText("flasks up"));
    expect(onOverride).toHaveBeenCalledWith([{ assumption_id: "config.elemental_overload", value: false }]);
  });

  it("marks overridden chips with the ↺ revert glyph", () => {
    const applied = new Map<string, unknown>([["config.chill_from_setup", false]]);
    const { container } = render(
      <VerdictCard
        card={{
          ...upgradeMapping,
          assumptions: [
            { id: "config.chill_from_setup", label: "enemy chilled", value: true, impactful: true, reversible: true as const },
          ],
        }}
        appliedOverrides={applied}
      />,
    );
    const chip = container.querySelector(".chip--overridden");
    expect(chip?.textContent).toContain("↺");
    expect(chip?.textContent).toContain("enemy chilled");
  });
});
