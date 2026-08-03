/**
 * Read-only clipboard change detector for the game's own Ctrl+C output.
 *
 * Electron does not expose a clipboard-change event, so the adapter samples
 * text at a fixed interval. Sampling never causes a server action by itself:
 * only a changed value with the stable PoE two-line header is emitted, once.
 * Item parsing/canonicalization remains server-owned.
 */

export const CLIPBOARD_POLL_MS = 100;

export interface ClipboardSource {
  readText: () => string;
}

export interface ClipboardWatcherDeps {
  clipboard: ClipboardSource;
  onItemText: (itemText: string) => void | Promise<void>;
  pollMs?: number;
}

export interface ClipboardWatcher {
  /** Baseline current clipboard contents, then begin watching for changes. */
  start: () => void;
  stop: () => void;
  /** One injectable/headless-testable sampling pass. */
  pollNow: () => Promise<void>;
}

/**
 * Recognition only, not parsing: raw PoE item text begins with non-empty
 * `Item Class:` and `Rarity:` lines. Preserve the original string for /diff.
 */
export function isPoeItemText(text: string): boolean {
  return /^(?:\uFEFF)?Item Class:[^\S\r\n]*\S[^\r\n]*\r?\nRarity:[^\S\r\n]*\S[^\r\n]*(?:\r?\n|$)/.test(
    text,
  );
}

export function createClipboardWatcher(deps: ClipboardWatcherDeps): ClipboardWatcher {
  const pollMs = deps.pollMs ?? CLIPBOARD_POLL_MS;
  let previousText: string | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;

  function readText(): string | undefined {
    try {
      return deps.clipboard.readText();
    } catch {
      // A temporarily locked/unavailable clipboard is not a player-facing
      // error and must never trigger a request. The next sample tries again.
      return undefined;
    }
  }

  async function pollNow(): Promise<void> {
    const text = readText();
    if (text === undefined) return;

    if (previousText === undefined) {
      previousText = text;
      return;
    }
    if (text === previousText) return;

    previousText = text;
    if (!isPoeItemText(text)) return;
    await deps.onItemText(text);
  }

  function start(): void {
    if (timer !== undefined) return;
    // Existing clipboard contents predate this watcher and therefore do not
    // prove an explicit user copy action (S2). Use them only as the baseline.
    previousText = readText();
    timer = setInterval(() => {
      void pollNow().catch(() => {
        // The diff flow maps request failures to shell states. This final
        // guard prevents an unexpected consumer error becoming an unhandled
        // rejection in Electron's main process.
      });
    }, pollMs);
  }

  function stop(): void {
    if (timer !== undefined) {
      clearInterval(timer);
      timer = undefined;
    }
    previousText = undefined;
  }

  return { start, stop, pollNow };
}
