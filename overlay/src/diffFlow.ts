/**
 * Hotkey → clipboard → /diff → state orchestration (docs/specs/verdict_card.md
 * §8.4). Pure and dependency-injected: no electron imports, so the whole flow
 * is unit-testable headless. The thin electron adapters live in main.ts,
 * window.ts, hotkey.ts, clipboardText.ts.
 *
 * Doctrine trace:
 * - S1: the clipboard (populated by the game's own Ctrl+C) is the only game
 *   input; it is read here exactly once per explicit hotkey press.
 * - S2: one server action per explicit user keypress — every onHotkey() call
 *   issues exactly one POST /diff. No polling, no auto-retry, no
 *   clipboard-change watchers.
 * - RULING-4: the FE never judges item text locally; even an empty clipboard
 *   is sent to the server, which alone decides (422 -> ERROR_UNPARSEABLE).
 * - RULING-20: errors are keyed off the HTTP status code ONLY; error bodies
 *   are never parsed or rendered.
 */
import { ApiError } from "../../web/src/generated/core/ApiError";
import type { VerdictCard } from "../../web/src/lib/verdictFormat";
import type { PostDiff } from "./diffRequest";
import { DIFF_TIMEOUT_MS, type ShellState } from "./shellState";

export interface DiffFlowDeps {
  /** S1: read-only clipboard access, called once per hotkey press. */
  readClipboard: () => string;
  /** The generated-client /diff call (see diffRequest.ts). */
  postDiff: PostDiff;
  /** Receives every state transition (main forwards it to the renderer). */
  onState: (state: ShellState) => void;
  /** RULING-19 timeout; injectable so tests don't wait 3 s. */
  timeoutMs?: number;
}

export interface DiffFlow {
  /** One explicit hotkey press = one fresh session = one /diff request. */
  onHotkey: () => Promise<void>;
}

export function createDiffFlow(deps: DiffFlowDeps): DiffFlow {
  const timeoutMs = deps.timeoutMs ?? DIFF_TIMEOUT_MS;
  // Generation counter: a newer keypress supersedes an in-flight request so a
  // late response can never overwrite a fresher session (§8.4: any state
  // ──hotkey──▶ LOADING).
  let generation = 0;

  async function onHotkey(): Promise<void> {
    const gen = ++generation;
    deps.onState({ kind: "LOADING" });

    const itemText = deps.readClipboard();
    const request = deps.postDiff(itemText);

    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        request.cancel(); // stop the in-flight HTTP request (RULING-19)
        reject(new Error(`diff timed out after ${timeoutMs} ms`));
      }, timeoutMs);
    });

    try {
      const card = await Promise.race([request as Promise<VerdictCard>, timeout]);
      if (gen !== generation) return; // superseded by a newer keypress
      deps.onState({ kind: "VERDICT", card });
    } catch (err) {
      if (gen !== generation) return;
      // RULING-20: HTTP status only, never the body.
      if (err instanceof ApiError && err.status === 404) {
        deps.onState({ kind: "ERROR_NO_BUILD" });
      } else if (err instanceof ApiError && err.status === 422) {
        deps.onState({ kind: "ERROR_UNPARSEABLE" });
      } else {
        // Network failure, timeout, cancel, 5xx — indistinguishable and
        // equally unactionable on the card (§8.2).
        deps.onState({ kind: "ERROR_UNAVAILABLE" });
      }
    } finally {
      clearTimeout(timer);
    }
  }

  return { onHotkey };
}
