/**
 * Electron main-process entry — the thin wiring layer. All logic lives in the
 * injected, headless-tested modules (diffFlow, diffRequest, serverEndpoint);
 * this file only connects them to electron primitives. Native verification of
 * the wiring (real hotkey delivery, real always-on-top, game-focus hide)
 * happens on the provisioned box (issue #34).
 */
import { app, ipcMain, shell } from "electron";
import { readItemText } from "./clipboardText";
import { createDiffFlow } from "./diffFlow";
import { bindGeneratedDiff } from "./diffRequest";
import { DEFAULT_HOTKEY, registerHotkey, unregisterAllHotkeys } from "./hotkey";
import { resolveServerBaseUrl, resolveWebAppUrl } from "./serverEndpoint";
import type { ShellState } from "./shellState";
import { createOverlayWindow } from "./window";

app.whenReady().then(() => {
  const win = createOverlayWindow();

  const flow = createDiffFlow({
    readClipboard: readItemText,
    postDiff: bindGeneratedDiff(resolveServerBaseUrl()),
    onState: (state: ShellState) => {
      if (state.kind !== "HIDDEN" && !win.isVisible()) win.showInactive();
      win.webContents.send("overlay:state", state);
    },
  });

  registerHotkey(DEFAULT_HOTKEY, () => {
    void flow.onHotkey();
  });

  // Tier-1 → Tier-2 promotion path (I7): the card's single details affordance
  // deep-links the web app in the system browser; the overlay itself never
  // grows a Tier-2 view.
  ipcMain.on("overlay:open-details", (_event, href: string) => {
    if (typeof href === "string" && href.startsWith("/")) {
      void shell.openExternal(resolveWebAppUrl() + href);
    }
  });

  app.on("will-quit", unregisterAllHotkeys);
});
