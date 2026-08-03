/**
 * Global hotkey registration. One hotkey, fixed in code — there is no hotkey
 * configuration UI and never will be in the overlay (I1, spec §10).
 * OVERLAY_HOTKEY is process-level config for packaged builds where the
 * default accelerator collides, NOT a settings surface (same class as
 * POE_ADVISOR_SERVER_URL in serverEndpoint.ts).
 *
 * SCAFFOLD NOTE: registration success and OS-level delivery are
 * native-verification ACs deferred to the provisioned box (issue #34).
 */
import { globalShortcut } from "electron";

export const DEFAULT_HOTKEY = "CommandOrControl+Alt+D";

/** OVERLAY_HOTKEY overrides the default accelerator; anything else falls back. */
export function resolveHotkeyAccelerator(env: NodeJS.ProcessEnv = process.env): string {
  const override = env.OVERLAY_HOTKEY?.trim();
  return override ? override : DEFAULT_HOTKEY;
}

/** The window surface the toggle needs (BrowserWindow in production). */
export interface HotkeyWindow {
  isVisible(): boolean;
  showInactive(): void;
  hide(): void;
}

/**
 * Show/hide toggle for the global hotkey. Showing goes through
 * showInactive() — NEVER show() or focus(): this is a game overlay, and
 * stealing focus mid-map is worse than not appearing at all.
 */
export function createVisibilityToggle(win: HotkeyWindow): () => void {
  return () => {
    if (win.isVisible()) {
      win.hide();
    } else {
      win.showInactive();
    }
  };
}

/**
 * Registers the accelerator, returning an unregister function. A failed
 * registration is logged and non-fatal: another app may already own the
 * accelerator, and that must not take the clipboard path down with it.
 */
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

/** The app surface the hotkey wiring needs (Electron App in production). */
export interface HotkeyApp {
  on(event: "will-quit", listener: () => void): void;
}

/**
 * Wires the global show/hide hotkey: registers the visibility toggle and
 * unregisters every shortcut on will-quit (alongside pipeline.stop in
 * main.ts). Registration failure stays non-fatal via registerHotkey.
 */
export function wireGlobalHotkey(
  app: HotkeyApp,
  win: HotkeyWindow,
  env: NodeJS.ProcessEnv = process.env,
): void {
  registerHotkey(resolveHotkeyAccelerator(env), createVisibilityToggle(win));
  app.on("will-quit", unregisterAllHotkeys);
}
