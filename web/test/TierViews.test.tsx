/**
 * TASK-301 (issue #13) — Tier-2 drivers + Tier-3 raw breakdown. Snapshot
 * coverage: loaded (drivers + raw tree), empty drivers (CAN'T EVALUATE, I5),
 * loading, contract-404, unreachable. Behavioral: one panel open issues
 * exactly one loadBreakdown call with the card's diff_id (S2: one tap = one
 * request; no prefetch).
 *
 * The components do no network I/O (sourceHygiene); `loadBreakdown` is a
 * stub. Fixture content comes from disk (web/mock/fixtures/breakdown/ and
 * contracts/fixtures/) — the same files the mock serves — never copies.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DetailsPanel } from "../src/components/DetailsPanel";
import { Tier2Drivers } from "../src/components/Tier2Drivers";
import { Tier3Breakdown } from "../src/components/Tier3Breakdown";
import type { Breakdown } from "../src/generated/models/Breakdown";
import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";

import upgradeMappingCardJson from "../../contracts/fixtures/upgrade_mapping.json";
import cantEvaluateCardJson from "../../contracts/fixtures/cant_evaluate_trigger_build.json";
import upgradeMappingBreakdownJson from "../mock/fixtures/breakdown/upgrade_mapping.json";
import cantEvaluateBreakdownJson from "../mock/fixtures/breakdown/cant_evaluate_trigger_build.json";

// JSON imports widen strings; fixtures.test.ts + breakdownFixture.test.ts
// prove conformance with the contract shapes, so bind to the types here.
const upgradeCard = upgradeMappingCardJson as VerdictCardData;
const cantEvaluateCard = cantEvaluateCardJson as VerdictCardData;
const upgradeBreakdown = upgradeMappingBreakdownJson as Breakdown;
const cantEvaluateBreakdown = cantEvaluateBreakdownJson as Breakdown;

describe("snapshot states (issue #13 acceptance criteria)", () => {
  it("Tier-2 drivers view — ranked mods with sign + number + bar (never color alone)", () => {
    const { container } = render(<Tier2Drivers drivers={upgradeBreakdown.drivers} />);
    expect(container).toMatchSnapshot();
  });

  it("Tier-3 raw breakdown view — the engine tree rendered verbatim", () => {
    const { container } = render(<Tier3Breakdown tree={upgradeBreakdown.pob_breakdown} />);
    expect(container).toMatchSnapshot();
  });

  it("empty drivers — CAN'T EVALUATE renders a first-class empty state (I5)", () => {
    const { container } = render(<Tier2Drivers drivers={cantEvaluateBreakdown.drivers} />);
    expect(container).toMatchSnapshot();
  });

  it("absent raw tree — first-class empty state", () => {
    const { container } = render(<Tier3Breakdown tree={undefined} />);
    expect(container).toMatchSnapshot();
  });

  it("DetailsPanel loading state", () => {
    const never = vi.fn<() => Promise<Breakdown>>().mockReturnValue(new Promise(() => {}));
    const { container } = render(<DetailsPanel card={upgradeCard} loadBreakdown={never} />);
    expect(container).toMatchSnapshot();
  });

  it("DetailsPanel loaded state — drivers + raw tree behind the one details affordance", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockResolvedValue(upgradeBreakdown);
    const { container } = render(<DetailsPanel card={upgradeCard} loadBreakdown={load} />);
    await screen.findByRole("table");
    expect(container).toMatchSnapshot();
  });

  it("DetailsPanel cant_evaluate — reasons list plus empty drivers and raw detection tree", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockResolvedValue(cantEvaluateBreakdown);
    const { container } = render(<DetailsPanel card={cantEvaluateCard} loadBreakdown={load} />);
    await screen.findByLabelText("Top stat drivers");
    expect(container).toMatchSnapshot();
  });

  it("DetailsPanel 404 — expired/unknown diff renders an alert", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockRejectedValue({ status: 404 });
    const { container } = render(<DetailsPanel card={upgradeCard} loadBreakdown={load} />);
    await screen.findByRole("alert");
    expect(container).toMatchSnapshot();
  });

  it("DetailsPanel unreachable — non-404 failure renders the unavailable alert", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockRejectedValue(new Error("down"));
    render(<DetailsPanel card={upgradeCard} loadBreakdown={load} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("alert").textContent).toContain("unavailable");
  });
});

describe("fetch contract (S2: one panel open = one GET /breakdown)", () => {
  it("fetches exactly once, with the card's diff_id", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockResolvedValue(upgradeBreakdown);
    render(<DetailsPanel card={upgradeCard} loadBreakdown={load} />);
    await screen.findByRole("table");
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith(upgradeCard.diff_id);
  });

  it("a new diff_id (chip re-diff) re-fetches exactly once for the new id", async () => {
    const load = vi.fn<(id: string) => Promise<Breakdown>>().mockResolvedValue(upgradeBreakdown);
    const { rerender } = render(<DetailsPanel card={upgradeCard} loadBreakdown={load} />);
    await screen.findByRole("table");
    const rediffed = { ...upgradeCard, diff_id: `${upgradeCard.diff_id}#ovr-abc123def456` };
    rerender(<DetailsPanel card={rediffed} loadBreakdown={load} />);
    await screen.findByText(`Details (diff ${rediffed.diff_id})`);
    expect(load).toHaveBeenCalledTimes(2);
    expect(load).toHaveBeenLastCalledWith(rediffed.diff_id);
  });
});

describe("backend review regressions", () => {
  it("ranks drivers by absolute contribution instead of trusting server order", () => {
    const drivers = [
      { mod_text: "small", contribution_pct: 1, stat: "ehp" },
      { mod_text: "largest", contribution_pct: -8, stat: "ehp" },
      { mod_text: "middle", contribution_pct: 4, stat: "total_dps" },
    ];

    render(<Tier2Drivers drivers={drivers} />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(
      rows.map((row) => within(row).getAllByRole("cell")[0].textContent),
    ).toEqual(["largest", "middle", "small"]);
  });
});
