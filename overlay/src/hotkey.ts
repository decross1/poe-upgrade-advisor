/**
 * Global hotkey registration. One hotkey with one process-level override
 * (the OVERLAY_HOTKEY env var, a constant — not a settings surface): there
 * is no hotkey configuration UI and never will be in the overlay (I1, §10).
 *
 * SCAFFOLD NOTE: registration success and OS-level delivery are
 * native-verification ACs deferred to the provisioned box (issue #34).
 */
import { globalShortcut } from "electron";

export const DEFAULT_HOTKEY = "CommandOrControl+Alt+D";

/** Returns an unregister function; main.ts wires unregisterAllHotkeys to will-quit. */
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
