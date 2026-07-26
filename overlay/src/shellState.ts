/**
 * Overlay UI states (docs/specs/verdict_card.md §8.4) as the single type
 * shared between the Electron main process and the renderer. Pure types +
 * constants only: this module must stay importable from BOTH sides (no
 * electron, no generated-client value imports).
 *
 * REDIFFING / chip re-diff is TASK-204 (#12) and deliberately absent here.
 */
import type { VerdictCard } from "../../web/src/lib/verdictFormat";

export type ShellState =
  | { kind: "HIDDEN" }
  | { kind: "LOADING" }
  | { kind: "VERDICT"; card: VerdictCard }
  | { kind: "ERROR_NO_BUILD" }
  | { kind: "ERROR_UNPARSEABLE" }
  | { kind: "ERROR_UNAVAILABLE" };

/**
 * RULING-19: 3000 ms without a /diff response means something is wrong
 * (I6 targets 300 ms p95) -> ERROR_UNAVAILABLE.
 */
export const DIFF_TIMEOUT_MS = 3000;

/**
 * RULING-19: render nothing for the first 120 ms of LOADING to avoid a
 * flash of the "Evaluating…" line on fast responses.
 */
export const LOADING_FLASH_GUARD_MS = 120;
