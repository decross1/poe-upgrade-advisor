/**
 * Electron main-process entry — the thin wiring layer. All logic lives in the
 * injected, headless-tested modules (clipboardPipeline, diffRequest,
 * serverEndpoint); this file only connects them to Electron primitives.
 */
import { app, ipcMain, shell } from "electron";
import { createClipboardPipeline } from "./clipboardPipeline";
import { electronClipboardSource } from "./clipboardText";
import { bindGeneratedDiff } from "./diffRequest";
import { DEFAULT_HOTKEY, registerHotkey, unregisterAllHotkeys } from "./hotkey";
import { resolveServerBaseUrl, resolveWebAppUrl } from "./serverEndpoint";
import type { ShellState } from "./shellState";
import { createOverlayWindow } from "./window";

app.whenReady().then(() => {
  const win = createOverlayWindow();

  const pipeline = createClipboardPipeline({
    clipboard: electronClipboardSource,
    postDiff: bindGeneratedDiff(resolveServerBaseUrl()),
    onState: (state: ShellState) => {
      if (state.kind !== "HIDDEN" && !win.isVisible()) win.showInactive();
      win.webContents.send("overlay:state", state);
    },
  });

  // Baseline after the renderer is ready so every detected capture can be
  // delivered to a subscribed card. Existing clipboard content is ignored.
  win.webContents.once("did-finish-load", pipeline.start);

  // Manual show/hide toggle — the interaction issue #97 names. Showing uses
  // showInactive() ONLY: the hotkey path must never steal game focus, so
  // show()/focus() are forbidden here (a stolen focus mid-map is worse than
  // no overlay). Registration failure is non-fatal (registerHotkey logs and
  // returns): another app may already own the accelerator, and that must not
  // take the clipboard path down with it.
  registerHotkey(process.env.OVERLAY_HOTKEY ?? DEFAULT_HOTKEY, () => {
    if (win.isVisible()) win.hide();
    else win.showInactive();
  });

  // Tier-1 → Tier-2 promotion path (I7): the card's single details affordance
  // deep-links the web app in the system browser; the overlay itself never
  // grows a Tier-2 view.
  ipcMain.on("overlay:open-details", (_event, href: string) => {
    if (typeof href === "string" && href.startsWith("/")) {
      void shell.openExternal(resolveWebAppUrl() + href);
    }
  });

  // I3 (§7): a chip tap in the renderer is one explicit user action — the
  // flow alone decides whether it becomes a /diff (S2; taps outside the
  // VERDICT phase or on display-only chips are swallowed there).
  ipcMain.on("overlay:chip-tap", (_event, assumption: Parameters<typeof pipeline.onChipTap>[0]) => {
    void pipeline.onChipTap(assumption);
  });

  app.on("will-quit", pipeline.stop);
  app.on("will-quit", unregisterAllHotkeys);
});
