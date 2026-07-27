/**
 * Captured item text → /diff → state orchestration
 * (docs/specs/verdict_card.md §8.4) AND chip tap → re-diff (§7/§8.3,
 * issue #64). Pure and
 * dependency-injected: no electron imports, so the whole flow is
 * unit-testable headless. Clipboard detection and Electron wiring live in
 * clipboardWatcher.ts, clipboardPipeline.ts, clipboardText.ts, and main.ts.
 *
 * The session logic is the SHARED state machine from web/src/lib/session.ts
 * (the same source the web app's useCardSession drives) — startSession /
 * beginRediff / resolveRediff / rejectRediff own every §7 rule; this module
 * only performs IO and projects SessionState onto ShellState. Never fork the
 * machine into the shell.
 *
 * Doctrine trace:
 * - S1: the clipboard (populated by the game's own Ctrl+C) is the only game
 *   input. This flow accepts the exact text supplied by that adapter.
 * - S2: one detected item capture or successful chip tap issues exactly one
 *   POST /diff. There is no retry or request polling. A tap outside the
 *   VERDICT phase (or on a display-only chip, RULING-14) is a no-op.
 * - The watcher only recognizes the stable PoE header shape. Parsing and
 *   canonicalization remain server-owned; this flow forwards text unchanged.
 * - RULING-18: a new item capture starts a fresh session — overrides never
 *   leak across items (startSession resets appliedOverrides).
 * - RULING-20: errors are keyed off the HTTP status code ONLY; error bodies
 *   are never parsed or rendered.
 * - RULING-21: a failed re-diff reverts the override and shows the transient
 *   sentence-slot message for TRANSIENT_MESSAGE_MS, then restores it. At most
 *   ONE transient timer is ever live: a later tap or item capture supersedes an
 *   earlier failure's message, so the earlier timer is cancelled and can
 *   never clear the newer message early (same ownership rule as the web
 *   app's useCardSession resetFlight).
 */
import { ApiError } from "../../web/src/generated/core/ApiError";
import type { Assumption, OverrideEntry } from "../../web/src/lib/overrides";
import {
  DIFF_TIMEOUT_MS,
  INITIAL_SESSION,
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
} from "../../web/src/lib/session";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";
import type { PostDiff } from "./diffRequest";
import type { ShellState } from "./shellState";

export interface DiffFlowDeps {
  /**
   * Deferred global-hotkey adapter. Production Stage 1 does not supply this;
   * retained so the existing headless hotkey-flow contract stays testable.
   */
  readClipboard?: () => string;
  /** The generated-client /diff call (see diffRequest.ts). */
  postDiff: PostDiff;
  /** Receives every state transition (main forwards it to the renderer). */
  onState: (state: ShellState) => void;
  /** RULING-19 timeout; injectable so tests don't wait 3 s. */
  timeoutMs?: number;
  /** RULING-21 transient-message duration; injectable for tests. */
  transientMs?: number;
}

export interface DiffFlow {
  /** One detected PoE item capture = one fresh session = one /diff request. */
  onItemText: (itemText: string) => Promise<void>;
  /** Deferred hotkey entry point; a no-op when no hotkey clipboard is wired. */
  onHotkey: () => Promise<void>;
  /**
   * One chip tap = one re-diff with the accumulated overrides (I3). No-op —
   * with NO request — unless the session is in the verdict phase showing a
   * boolean chip (§8.3's chips-disabled is enforced HERE, not just in the
   * renderer, so a stale tap can never fan out a second request).
   */
  onChipTap: (assumption: Assumption) => Promise<void>;
}

/** SessionState → the renderer's ShellState projection. */
export function toShellState(session: SessionState): ShellState {
  switch (session.phase.kind) {
    case "idle":
      return { kind: "HIDDEN" };
    case "loading":
      return { kind: "LOADING" };
    case "verdict": {
      // The card is guaranteed present in the verdict phase (resolveInitial /
      // resolveRediff set it before entering); a missing card is a flow bug.
      if (session.card === null) return { kind: "ERROR_UNAVAILABLE" };
      return {
        kind: "VERDICT",
        card: session.card,
        appliedOverrides: overrideEntries(session.appliedOverrides),
        transientMessage: session.transientMessage,
      };
    }
    case "rediffing": {
      if (session.card === null) return { kind: "ERROR_UNAVAILABLE" };
      return {
        kind: "REDIFFING",
        card: session.card,
        appliedOverrides: overrideEntries(session.appliedOverrides),
        pendingChipId: session.phase.pendingChipId,
      };
    }
    case "error":
      switch (session.phase.error) {
        case "no_build":
          return { kind: "ERROR_NO_BUILD" };
        case "unparseable":
          return { kind: "ERROR_UNPARSEABLE" };
        case "unavailable":
          return { kind: "ERROR_UNAVAILABLE" };
      }
  }
}

function overrideEntries(map: ReadonlyMap<string, unknown>): OverrideEntry[] {
  return [...map.entries()].map(([assumption_id, value]) => ({ assumption_id, value }));
}

export function createDiffFlow(deps: DiffFlowDeps): DiffFlow {
  const timeoutMs = deps.timeoutMs ?? DIFF_TIMEOUT_MS;
  const transientMs = deps.transientMs ?? TRANSIENT_MESSAGE_MS;
  let session: SessionState = INITIAL_SESSION;
  // Generation counter: a newer capture supersedes any in-flight request so
  // a late response can never overwrite a fresher session (§8.4: any state
  // ──capture──▶ LOADING). Chip taps do NOT bump it — they belong to the
  // current session — but they capture it to detect their own supersession.
  let generation = 0;
  // RULING-21: the single live transient-message timer (if any). The flow's
  // generation counter only guards against supersession by a HOTKEY; two
  // failed re-diffs within one session share a generation, so without this
  // the first failure's stale timer would clear the second failure's message
  // before its full TRANSIENT_MESSAGE_MS (PR #84 review round 1).
  let transientTimer: ReturnType<typeof setTimeout> | undefined;

  /** Invalidate any pending transient timer; the newest action owns the card. */
  function cancelTransientTimer(): void {
    if (transientTimer !== undefined) {
      clearTimeout(transientTimer);
      transientTimer = undefined;
    }
  }

  function emit(): void {
    deps.onState(toShellState(session));
  }

  /** One /diff request raced against the RULING-19 timeout (cancel on expiry). */
  async function request(body: DiffRequestBody): Promise<VerdictCard> {
    const req = deps.postDiff(body);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        req.cancel(); // stop the in-flight HTTP request (RULING-19)
        reject(new Error(`diff timed out after ${timeoutMs} ms`));
      }, timeoutMs);
    });
    try {
      return await Promise.race([req as Promise<VerdictCard>, timeout]);
    } finally {
      clearTimeout(timer);
    }
  }

  async function onItemText(itemText: string): Promise<void> {
    const gen = ++generation;
    cancelTransientTimer(); // the fresh session owns the card (RULING-18)
    session = startSession(itemText);
    emit(); // LOADING

    try {
      const card = await request(initialDiffBody(session.itemText as string));
      if (gen !== generation) return; // superseded by a newer capture
      session = resolveInitial(session, card);
      emit(); // VERDICT
    } catch (err) {
      if (gen !== generation) return;
      // RULING-20: HTTP status only, never the body.
      const status = err instanceof ApiError ? err.status : undefined;
      session = failInitial(session, errorFromStatus(status));
      emit(); // ERROR_NO_BUILD / ERROR_UNPARSEABLE / ERROR_UNAVAILABLE
    }
  }

  async function onHotkey(): Promise<void> {
    if (deps.readClipboard === undefined) return;
    await onItemText(deps.readClipboard());
  }

  async function onChipTap(assumption: Assumption): Promise<void> {
    const begun = beginRediff(session, assumption);
    if (begun === null) return; // no state change, NO request (S2)
    const gen = generation; // taps join the current session; captures supersede
    cancelTransientTimer(); // the new tap supersedes any earlier failure's message
    session = begun.state;
    emit(); // REDIFFING (pending chip, strip disabled)

    try {
      const card = await request(begun.body);
      if (gen !== generation) return; // superseded by a newer capture
      session = resolveRediff(session, card);
      emit(); // VERDICT — the pending mutation commits (§7.3)
    } catch {
      // RULING-21: ANY failure (non-200, network, timeout) reverts.
      if (gen !== generation) return;
      session = rejectRediff(session);
      emit(); // VERDICT — reverted, transient retry message in sentence slot
      cancelTransientTimer(); // this failure now owns the sentence slot
      transientTimer = setTimeout(() => {
        transientTimer = undefined;
        if (gen !== generation) return; // a newer session owns the card now
        session = clearTransient(session);
        emit(); // VERDICT — original sentence restored
      }, transientMs);
    }
  }

  return { onItemText, onHotkey, onChipTap };
}
