/**
 * Overlay UI states (docs/specs/verdict_card.md §8.4) as the single type
 * shared between the Electron main process and the renderer. Pure types +
 * constants only: this module must stay importable from BOTH sides (no
 * electron, no generated-client value imports).
 *
 * VERDICT/REDIFFING carry the session projection the card needs (§7): the
 * accumulated overrides and the re-diff pending/transient markers. The
 * session itself (itemText/preset) lives in the main-process flow
 * (diffFlow.ts), which drives the SHARED state machine from
 * web/src/lib/session.ts — the same source the web app uses (issue #64:
 * reuse, never fork). Overrides cross the IPC bridge as OverrideEntry[]
 * (JSON-safe); the renderer rehydrates them into the Map the shared card
 * component consumes.
 */
import type { OverrideEntry } from "../../web/src/lib/overrides";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";

export type ShellState =
  | { kind: "HIDDEN" }
  | { kind: "LOADING" }
  | {
      kind: "VERDICT";
      card: VerdictCard;
      /** Full accumulated session overrides (RULING-17); empty when none. */
      appliedOverrides: OverrideEntry[];
      /** §8.3 [RULING-21]: transient replacement for the sentence slot. */
      transientMessage: string | null;
    }
  | {
      kind: "REDIFFING";
      card: VerdictCard;
      appliedOverrides: OverrideEntry[];
      /** §8.3: the tapped chip shows the inline spinner; strip disabled (S2). */
      pendingChipId: string;
    }
  | { kind: "ERROR_NO_BUILD" }
  | { kind: "ERROR_UNPARSEABLE" }
  | { kind: "ERROR_UNAVAILABLE" };

/**
 * RULING-19 timings (3000 ms diff timeout -> ERROR_UNAVAILABLE; 120 ms
 * LOADING flash guard) — re-exported from the shared session machine so
 * shell and web read one source (web/src/lib/session.ts owns the literals).
 */
export { DIFF_TIMEOUT_MS, LOADING_FLASH_GUARD_MS } from "../../web/src/lib/session";
