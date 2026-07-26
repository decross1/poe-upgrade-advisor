/**
 * One-tap override logic for the assumptions chip (Doctrine I3). Emission only:
 * HTTP wiring is TASK-206; full re-diff UX is TASK-204.
 */
import type { components } from "./api-types";

export type Assumption = components["schemas"]["Assumption"];

/** Wire shape of one entry in POST /api/v0/diff's `overrides` array.
 *  `assumption_id` is Assumption.id, never source_rule. [RULING-16] */
export interface OverrideEntry {
  assumption_id: string;
  value: unknown;
}

/** Tappability is decided by VALUE TYPE, not by `impactful` or `reversible`:
 *  boolean values flip; anything else is display-only in MVP. [RULING-14/15] */
export function isTappable(assumption: Assumption): boolean {
  return typeof assumption.value === "boolean";
}

/**
 * Toggle one boolean assumption against the session's applied overrides and
 * return the FULL accumulated overrides array (every entry, because /diff is
 * stateless). If the assumption was already overridden, the tap removes the
 * override (restores inference). [RULING-17, spec §7.1]
 */
export function toggleOverride(
  applied: ReadonlyMap<string, unknown>,
  assumption: Assumption,
): OverrideEntry[] {
  const next = new Map(applied);
  if (next.has(assumption.id)) {
    next.delete(assumption.id);
  } else {
    next.set(assumption.id, !assumption.value);
  }
  return [...next.entries()].map(([assumption_id, value]) => ({ assumption_id, value }));
}
