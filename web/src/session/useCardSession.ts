/**
 * React wiring for the card session state machine (src/lib/session.ts) —
 * the ONE place hand-written UI code touches the network, and it does so only
 * through the generated contract client (DefaultService.diffItem). The
 * server URL is the contract's servers[0].url; TASK-202 makes it real.
 *
 * Timing rules (docs/specs/verdict_card.md §8, RULING-19/21):
 *  - LOADING renders nothing for the first 120 ms (flash guard);
 *  - any /diff older than 3000 ms is cancelled and treated as failure;
 *  - re-diff failure reverts and shows the transient message for 3000 ms.
 *
 * S2: every request traces to an explicit user action (evaluate = hotkey,
 * tapChip = chip tap). No polling, no auto-retry, no batching.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { DefaultService } from "../generated/services/DefaultService";
import type { CancelablePromise } from "../generated/core/CancelablePromise";
import type { Assumption } from "../lib/overrides";
import type { VerdictCard } from "../lib/verdictFormat";

import {
  DIFF_TIMEOUT_MS,
  INITIAL_SESSION,
  LOADING_FLASH_GUARD_MS,
  TRANSIENT_MESSAGE_MS,
  beginRediff,
  clearTransient,
  errorFromStatus,
  failInitial,
  initialDiffBody,
  rejectRediff,
  resolveInitial,
  resolveRediff,
  startSession,
  type DiffRequestBody,
  type SessionState,
} from "../lib/session";

export type DiffFn = (body: DiffRequestBody) => CancelablePromise<VerdictCard>;

// The generated client's models and src/lib/api-types.ts are two generators'
// views of the SAME contract wire shape (both from contracts/openapi.yaml);
// the codegen's nominal enum types don't cross-assign, so the boundary cast
// is confined to this one line. Hand-written code uses api-types throughout.
const contractDiff: DiffFn = (body) =>
  DefaultService.diffItem(body) as unknown as CancelablePromise<VerdictCard>;

/** RULING-20: the status code is the only signal; error bodies are never read. */
function statusOf(error: unknown): number | undefined {
  return (error as { status?: unknown } | null)?.status as number | undefined;
}

export interface CardSession {
  state: SessionState;
  /** §8.1: true once LOADING may render (120 ms flash guard elapsed). */
  loadingVisible: boolean;
  /** Hotkey press: begin a fresh session for this item text. */
  evaluate: (itemText: string) => void;
  /** Chip tap: one re-diff with the accumulated overrides (I3). */
  tapChip: (assumption: Assumption) => void;
}

export function useCardSession(diffFn: DiffFn = contractDiff): CardSession {
  const [state, setState] = useState<SessionState>(INITIAL_SESSION);
  const [loadingVisible, setLoadingVisible] = useState(false);
  const stateRef = useRef(state);
  stateRef.current = state;
  // Stale-response guard: bumped by every new request/action; late
  // resolutions from superseded requests are dropped.
  const seqRef = useRef(0);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const inFlightRef = useRef<CancelablePromise<VerdictCard> | null>(null);

  const clearTimers = () => {
    for (const t of timersRef.current) clearTimeout(t);
    timersRef.current = [];
  };
  const later = (ms: number, fn: () => void) => {
    timersRef.current.push(setTimeout(fn, ms));
  };

  /** Invalidate and abort any in-flight request (new session or new tap). */
  const resetFlight = () => {
    seqRef.current += 1;
    clearTimers();
    inFlightRef.current?.cancel();
    inFlightRef.current = null;
  };

  useEffect(() => resetFlight, []);

  const evaluate = useCallback(
    (itemText: string) => {
      resetFlight();
      setLoadingVisible(false);
      setState(startSession(itemText));
      const seq = seqRef.current;
      later(LOADING_FLASH_GUARD_MS, () => setLoadingVisible(true));
      const req = diffFn(initialDiffBody(itemText));
      inFlightRef.current = req;
      later(DIFF_TIMEOUT_MS, () => req.cancel()); // §8.1 timeout → ERROR_UNAVAILABLE
      req
        .then((card) => {
          if (seq !== seqRef.current) return;
          clearTimers();
          setState((s) => resolveInitial(s, card));
        })
        .catch((error: unknown) => {
          if (seq !== seqRef.current) return;
          clearTimers();
          setState((s) => failInitial(s, errorFromStatus(statusOf(error))));
        });
    },
    [diffFn],
  );

  const tapChip = useCallback(
    (assumption: Assumption) => {
      const begun = beginRediff(stateRef.current, assumption);
      if (!begun) return; // not in VERDICT phase, or display-only chip
      resetFlight();
      setState(begun.state);
      const seq = seqRef.current;
      const req = diffFn(begun.body);
      inFlightRef.current = req;
      later(DIFF_TIMEOUT_MS, () => req.cancel()); // §8.3: timeout counts as failure
      req
        .then((card) => {
          if (seq !== seqRef.current) return;
          clearTimers();
          setState((s) => resolveRediff(s, card));
        })
        .catch(() => {
          // §8.3 [RULING-21]: ANY failure (non-200, network, timeout) reverts.
          if (seq !== seqRef.current) return;
          clearTimers();
          setState((s) => rejectRediff(s));
          later(TRANSIENT_MESSAGE_MS, () => setState((s) => clearTransient(s)));
        });
    },
    [diffFn],
  );

  return { state, loadingVisible, evaluate, tapChip };
}
