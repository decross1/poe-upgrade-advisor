/**
 * Card session state machine — the TASK-204 interaction half of the
 * assumptions chip (Doctrine I3). Pure functions only: no React, no network,
 * no timers. Every rule traces to docs/specs/verdict_card.md §7/§8; the React
 * wiring lives in src/session/useCardSession.ts.
 *
 * One hotkey press = one session (§7). The session owns: the item text, the
 * echoed preset, and the accumulated one-tap overrides.
 */
import type { components } from "./api-types";
import { isTappable, toggleOverride, type Assumption, type OverrideEntry } from "./overrides";
import type { VerdictCard } from "./verdictFormat";

export type Preset = components["schemas"]["VerdictCard"]["preset"];

/** §8.1 [RULING-19]: render nothing for the first 120 ms of LOADING. */
export const LOADING_FLASH_GUARD_MS = 120;
/** §8.1/§8.3 [RULING-19]: any /diff without a response after 3000 ms fails. */
export const DIFF_TIMEOUT_MS = 3000;
/** §8.3 [RULING-21]: the re-diff failure message shows for 3000 ms. */
export const TRANSIENT_MESSAGE_MS = 3000;

/** §8.3 [RULING-21] — exact card text; reuses the sentence slot (I2-safe). */
export const RECOMPUTE_FAILED_MESSAGE = "Couldn't recompute — tap the chip to retry.";

/** §8.2 — exact card texts for the three initial-diff error states. */
export const NO_BUILD_MESSAGE = "No build imported.";
export const UNPARSEABLE_MESSAGE = "Couldn't read that item — copy it in game with Ctrl+C.";
export const UNAVAILABLE_MESSAGE = "Advisor engine isn't running.";

/** §8.2 error states. Initial-diff failures only; re-diff failure is §8.3. */
export type SessionError = "no_build" | "unparseable" | "unavailable";

export type SessionPhase =
  | { kind: "idle" } // before the first hotkey press; renders nothing
  | { kind: "loading" } // §8.1: initial diff in flight
  | { kind: "verdict" } // card rendered, boolean chips live
  | { kind: "rediffing"; pendingChipId: string } // §8.3: chip tap in flight
  | { kind: "error"; error: SessionError };

export interface SessionState {
  phase: SessionPhase;
  /** Canonicalized clipboard text of this session; resent verbatim on every re-diff (§7). */
  itemText: string | null;
  /** Echo of the last response's `preset` field (§7 CardSession). */
  preset: Preset | undefined;
  card: VerdictCard | null;
  /** Overrides the server has confirmed (or none yet). [RULING-17] */
  appliedOverrides: ReadonlyMap<string, unknown>;
  /** The mutation a re-diff is trying to commit; undone on failure. [RULING-21] */
  pendingOverrides: ReadonlyMap<string, unknown> | null;
  /** §8.3 [RULING-21]: transient replacement for the sentence slot. */
  transientMessage: string | null;
}

export const INITIAL_SESSION: SessionState = {
  phase: { kind: "idle" },
  itemText: null,
  preset: undefined,
  card: null,
  appliedOverrides: new Map<string, unknown>(),
  pendingOverrides: null,
  transientMessage: null,
};

/** Request body for POST /api/v0/diff (generated-client shape). */
export interface DiffRequestBody {
  item_text: string;
  preset?: "mapping" | "bossing";
  overrides?: OverrideEntry[];
}

/** New hotkey press = fresh session: overrides NEVER leak across items. [RULING-18] */
export function startSession(itemText: string): SessionState {
  return { ...INITIAL_SESSION, phase: { kind: "loading" }, itemText };
}

/**
 * Body of the session's first /diff: item text only. The overlay omits
 * `preset` on the first diff of a session (build default applies, §10) and
 * never sends `balanced` (RULING-22) — the request type encodes both.
 */
export function initialDiffBody(itemText: string): DiffRequestBody {
  return { item_text: itemText };
}

/** §7.3: on 200, replace the entire card. */
export function resolveInitial(state: SessionState, card: VerdictCard): SessionState {
  if (state.phase.kind !== "loading") return state;
  return { ...state, phase: { kind: "verdict" }, card, preset: card.preset };
}

/** §8.2: initial-diff failure → one of the three minimal error states. */
export function failInitial(state: SessionState, error: SessionError): SessionState {
  if (state.phase.kind !== "loading") return state;
  return { ...state, phase: { kind: "error", error } };
}

/**
 * RULING-20: error handling keys off the HTTP status code ONLY — never parse
 * an error body. Unknown/absent status (network down, timeout cancel, 5xx) is
 * ERROR_UNAVAILABLE.
 */
export function errorFromStatus(status: number | undefined): SessionError {
  if (status === 404) return "no_build";
  if (status === 422) return "unparseable";
  return "unavailable";
}

function entries(map: ReadonlyMap<string, unknown>): OverrideEntry[] {
  return [...map.entries()].map(([assumption_id, value]) => ({ assumption_id, value }));
}

/**
 * §7 step 1–2: toggle one boolean assumption and begin the re-diff. Returns
 * the next state plus the exact request body, or null when the tap must be a
 * no-op (not in VERDICT phase — covers §8.3's chips-disabled S2 protection —
 * or a non-boolean/display-only chip, RULING-14). Overrides accumulate: the
 * body carries the FULL set, because /diff is stateless. [RULING-17]
 */
export function beginRediff(
  state: SessionState,
  assumption: Assumption,
): { state: SessionState; body: DiffRequestBody } | null {
  if (state.phase.kind !== "verdict" || state.itemText === null || !isTappable(assumption)) {
    return null;
  }
  const next = new Map(toggleOverride(state.appliedOverrides, assumption).map((o) => [o.assumption_id, o.value]));
  const body: DiffRequestBody = {
    item_text: state.itemText,
    // §7: echo the session preset. Never send `balanced` (RULING-22: it is
    // response-only tolerance; no presets/balanced.yaml exists).
    preset: state.preset === "balanced" ? undefined : state.preset,
    overrides: entries(next),
  };
  return {
    state: {
      ...state,
      phase: { kind: "rediffing", pendingChipId: assumption.id },
      pendingOverrides: next,
      transientMessage: null,
    },
    body,
  };
}

/** §7.3: re-diff 200 → replace the entire card; the pending mutation commits. */
export function resolveRediff(state: SessionState, card: VerdictCard): SessionState {
  if (state.phase.kind !== "rediffing") return state;
  return {
    ...state,
    phase: { kind: "verdict" },
    card,
    preset: card.preset,
    appliedOverrides: state.pendingOverrides ?? state.appliedOverrides,
    pendingOverrides: null,
  };
}

/**
 * §8.3 [RULING-21]: re-diff failure (any non-200/timeout) → revert: the card
 * and appliedOverrides are untouched (the mutation is dropped), and the
 * sentence slot carries the transient retry message.
 */
export function rejectRediff(state: SessionState): SessionState {
  if (state.phase.kind !== "rediffing") return state;
  return { ...state, phase: { kind: "verdict" }, pendingOverrides: null, transientMessage: RECOMPUTE_FAILED_MESSAGE };
}

/** §8.3: after TRANSIENT_MESSAGE_MS, restore the original sentence. */
export function clearTransient(state: SessionState): SessionState {
  if (state.transientMessage === null) return state;
  return { ...state, transientMessage: null };
}
