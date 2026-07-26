/**
 * TASK-301 review round 2 (issue #13, PR #49) — Doctrine I7 regression:
 * Tier 1 → Tier 2 must happen on the CARD's details tap. Round 1 found the
 * card's detailsHref="#details" anchor inert while a second, duplicate
 * "Open details (Tier 2/3)" link was the only control wired to the panel.
 * This test renders the real demo App (client seams stubbed — no network;
 * the defaults stay the generated client) and drives the card's own
 * affordance.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CancelablePromise } from "../src/generated/core/CancelablePromise";
import type { Breakdown } from "../src/generated/models/Breakdown";
import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";
import type { DiffFn } from "../src/session/useCardSession";
import { App } from "../src/demo/App";

import upgradeMappingCardJson from "../../contracts/fixtures/upgrade_mapping.json";
import upgradeMappingBreakdownJson from "../mock/fixtures/breakdown/upgrade_mapping.json";

const upgradeCard = upgradeMappingCardJson as VerdictCardData;
const upgradeBreakdown = upgradeMappingBreakdownJson as Breakdown;

function immediateDiff(card: VerdictCardData): DiffFn {
  return () =>
    new CancelablePromise<VerdictCardData>((resolve) => {
      resolve(card);
    });
}

describe("I7: the card's own details affordance opens Tier 2/3", () => {
  it("clicking it requests the breakdown and shows the panel; exactly one details control exists", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockResolvedValue(upgradeBreakdown);
    render(<App diffFn={immediateDiff(upgradeCard)} loadBreakdown={load} />);

    // Exactly ONE details affordance on the page, and it is the card's — the
    // demo's duplicate "Open details (Tier 2/3)" link is gone.
    const detailsLink = await screen.findByRole("link", { name: "Open details ▸" });
    expect(screen.getAllByRole("link", { name: /details/i })).toHaveLength(1);
    expect(detailsLink.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(detailsLink);

    // The tap issues the one breakdown request keyed by the card's diff_id…
    await screen.findByRole("table");
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith(upgradeCard.diff_id);
    // …and the panel shows Tier-2 drivers + Tier-3 raw tree.
    expect(screen.getByLabelText("Top stat drivers")).not.toBeNull();
    expect(screen.getByLabelText("Raw engine breakdown")).not.toBeNull();
    expect(detailsLink.getAttribute("aria-expanded")).toBe("true");

    // Tapping the same affordance again hides the panel — no second request.
    fireEvent.click(screen.getByRole("link", { name: "Hide details ▾" }));
    expect(screen.queryByLabelText("Top stat drivers")).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
  });
});
