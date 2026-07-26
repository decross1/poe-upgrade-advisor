/**
 * Global hotkey registration. One hotkey, fixed in code — there is no hotkey
 * configuration UI and never will be in the overlay (I1, spec §10).
 *
 * SCAFFOLD NOTE: registration success and OS-level delivery are
 * native-verification ACs deferred to the provisioned box (issue #34).
 */
import { globalShortcut } from "electron";

export const DEFAULT_HOTKEY = "CommandOrControl+Shift+D";

/** Returns an unregister function (wired to app will-quit in main.ts). */
export function registerHotkey(accelerator: string, onTrigger: () => void): () => void {
  const ok = globalShortcut.register(accelerator, onTrigger);
  if (!ok) {
    // Logged, not rendered: the card has no error slot for shell faults (I2).
    console.error(`overlay: failed to register hotkey "${accelerator}"`);
  }
  return () => globalShortcut.unregister(accelerator);
}

export function unregisterAllHotkeys(): void {
  globalShortcut.unregisterAll();
}
