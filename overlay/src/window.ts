/**
 * Electron window shell (ADR-0004 fallback stack). Fixed geometry, frameless,
 * always-on-top, no taskbar entry — and NO settings surface: every option is
 * a compile-time constant (I1).
 *
 * SCAFFOLD NOTE (issue #11, native-verification ACs deferred to issue #34):
 * alwaysOnTop, windowed-fullscreen coexistence, and "hide when the game loses
 * focus" are CONFIGURED here but can only be VERIFIED against the real game
 * on the provisioned box. Nothing below simulates or fakes that verification.
 */
import { BrowserWindow } from "electron";
import path from "node:path";

/** Card is fixed-width 340 px logical (docs/specs/verdict_card.md §1). */
export const OVERLAY_WIDTH_PX = 340;
/** Enough for the worst-case card (6 chips wrapping 2 rows); content clips. */
export const OVERLAY_HEIGHT_PX = 240;

export function createOverlayWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: OVERLAY_WIDTH_PX,
    height: OVERLAY_HEIGHT_PX,
    useContentSize: true,
    frame: false,
    resizable: false,
    maximizable: false,
    fullscreenable: false, // the overlay itself never takes focus from the game
    alwaysOnTop: true, // verified on the provisioned box (issue #34)
    skipTaskbar: true,
    show: false, // shown on first detected item capture, hidden otherwise
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  win.setMenu(null);
  win.loadFile(path.join(__dirname, "index.html"));
  return win;
}
