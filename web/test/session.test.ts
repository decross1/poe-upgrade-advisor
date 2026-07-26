/**
 * Pure card-session state machine (src/lib/session.ts) — the TASK-204 rules
 * of docs/specs/verdict_card.md §7/§8 with no React and no network.
 */
import { describe, expect, it } from "vitest";
import {
  INITIAL_SESSION,
  RECOMPUTE_FAILED_MESSAGE,
  beginRediff,
  clearTransient,
  errorFromStatus,
  failInitial,
  initialDiffBody,
  rejectRediff,
  resolveInitial,
  resolveRediff,
  startSession,
  type SessionState,
} from "../src/lib/session";
import type { VerdictCard as VerdictCardData } from "../src/lib/verdictFormat";

import upgradeMappingJson from "../../contracts/fixtures/upgrade_mapping.json";
import sidegradeBalancedJson from "../../contracts/fixtures/sidegrade_balanced_low_confidence.json";

const upgradeMapping = upgradeMappingJson as VerdictCardData;
const sidegradeBalanced = sidegradeBalancedJson as VerdictCardData;

const CRIT = upgradeMapping.assumptions.find((a) => a.id === "config.elemental_overload")!;
const FLASKS = upgradeMapping.assumptions.find((a) => a.id === "config.flasks_up")!;
const SKILL = upgradeMapping.assumptions.find((a) => a.id === "main_skill.most_linked_highest_dps")!;

const ITEM = "Rarity: RARE\nDoom Wrap\n@fixture:upgrade_mapping";

/** Fast-forward a session into VERDICT with the upgrade card. */
function verdictSession(): SessionState {
  return resolveInitial(startSession(ITEM), upgradeMapping);
}

describe("session lifecycle (§7, RULING-18)", () => {
  it("a new session clears overrides and never leaks them across items", () => {
    const begun = beginRediff(verdictSession(), CRIT)!;
    const after = resolveRediff(begun.state, upgradeMapping);
    expect(after.appliedOverrides.size).toBe(1);

    const fresh = startSession("Rarity: RARE\nNew Item");
    expect(fresh.appliedOverrides.size).toBe(0);
    expect(fresh.pendingOverrides).toBeNull();
    expect(fresh.card).toBeNull();
    expect(fresh.phase).toEqual({ kind: "loading" });
  });

  it("the session's first /diff omits preset (build default, §10) and overrides", () => {
    expect(initialDiffBody(ITEM)).toEqual({ item_text: ITEM });
  });
});

describe("beginRediff request shape (RULING-16/17, §7)", () => {
  it("one tap → item text + echoed preset + the full override set", () => {
    const { body, state } = beginRediff(verdictSession(), CRIT)!;
    expect(body).toEqual({
      item_text: ITEM,
      preset: "mapping",
      overrides: [{ assumption_id: "config.elemental_overload", value: false }],
    });
    expect(state.phase).toEqual({ kind: "rediffing", pendingChipId: "config.elemental_overload" });
  });

  it("overrides accumulate across taps (stateless /diff gets the full set)", () => {
    const first = beginRediff(verdictSession(), CRIT)!;
    const committed = resolveRediff(first.state, upgradeMapping);
    const second = beginRediff(committed, FLASKS)!;
    expect(second.body.overrides).toEqual([
      { assumption_id: "config.elemental_overload", value: false },
      { assumption_id: "config.flasks_up", value: false },
    ]);
  });

  it("tapping an overridden chip removes the override (restore inference, §7.1)", () => {
    const first = beginRediff(verdictSession(), CRIT)!;
    const committed = resolveRediff(first.state, upgradeMapping);
    const second = beginRediff(committed, CRIT)!;
    expect(second.body.overrides).toEqual([]);
  });

  it("is a no-op outside VERDICT phase (§8.3 chips-disabled, S2) and for non-boolean chips (RULING-14)", () => {
    expect(beginRediff(INITIAL_SESSION, CRIT)).toBeNull();
    expect(beginRediff(startSession(ITEM), CRIT)).toBeNull();
    expect(beginRediff(verdictSession(), SKILL)).toBeNull(); // string value: display-only
    const inFlight = beginRediff(verdictSession(), CRIT)!;
    expect(beginRediff(inFlight.state, FLASKS)).toBeNull(); // already rediffing
  });

  it("never echoes the reserved 'balanced' preset into a request (RULING-22)", () => {
    const balancedSession = resolveInitial(startSession(ITEM), sidegradeBalanced);
    const balancedChip = balancedSession.card!.assumptions.find((a) => typeof a.value === "boolean")!;
    const { body } = beginRediff(balancedSession, balancedChip)!;
    expect(body.preset).toBeUndefined();
    expect(JSON.stringify(body)).not.toContain("balanced");
  });
});

describe("resolve/reject (§7.3, §8.3 RULING-21)", () => {
  it("resolve commits the pending mutation and replaces the entire card", () => {
    const begun = beginRediff(verdictSession(), CRIT)!;
    const rediffed: VerdictCardData = { ...upgradeMapping, diff_id: "d-8f2c41a7#ovr-deadbeef1234" };
    const after = resolveRediff(begun.state, rediffed);
    expect(after.phase).toEqual({ kind: "verdict" });
    expect(after.card?.diff_id).toBe("d-8f2c41a7#ovr-deadbeef1234");
    expect([...after.appliedOverrides.entries()]).toEqual([["config.elemental_overload", false]]);
    expect(after.pendingOverrides).toBeNull();
  });

  it("reject reverts: card and appliedOverrides untouched, mutation dropped, transient set", () => {
    const begun = beginRediff(verdictSession(), CRIT)!;
    const after = rejectRediff(begun.state);
    expect(after.phase).toEqual({ kind: "verdict" });
    expect(after.card).toBe(upgradeMapping);
    expect(after.appliedOverrides.size).toBe(0);
    expect(after.pendingOverrides).toBeNull();
    expect(after.transientMessage).toBe(RECOMPUTE_FAILED_MESSAGE);

    const cleared = clearTransient(after);
    expect(cleared.transientMessage).toBeNull();
  });

  it("stale resolve/reject outside REDIFFING is ignored", () => {
    const verdict = verdictSession();
    expect(resolveRediff(verdict, upgradeMapping)).toBe(verdict);
    expect(rejectRediff(verdict)).toBe(verdict);
    expect(resolveInitial(verdict, upgradeMapping)).toBe(verdict);
    expect(failInitial(verdict, "unavailable")).toBe(verdict);
  });
});

describe("error mapping (§8.2, RULING-20: status code only)", () => {
  it("404 → no_build, 422 → unparseable, anything else/absent → unavailable", () => {
    expect(errorFromStatus(404)).toBe("no_build");
    expect(errorFromStatus(422)).toBe("unparseable");
    expect(errorFromStatus(500)).toBe("unavailable");
    expect(errorFromStatus(undefined)).toBe("unavailable");
  });

  it("initial-diff failure lands in the matching error state", () => {
    const failed = failInitial(startSession(ITEM), errorFromStatus(404));
    expect(failed.phase).toEqual({ kind: "error", error: "no_build" });
  });
});
