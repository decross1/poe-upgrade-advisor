/**
 * Electron main-process entry — the thin wiring layer. All logic lives in the
 * injected, headless-tested modules (clipboardPipeline, diffRequest,
 * serverEndpoint); this file only connects them to Electron primitives.
 */
import { app, ipcMain, shell } from "electron";
import { createClipboardPipeline } from "./clipboardPipeline";
import { electronClipboardSource } from "./clipboardText";
import { bindGeneratedDiff } from "./diffRequest";
import { wireGlobalHotkey } from "./hotkey";
import { resolveServerBaseUrl, resolveWebAppUrl } from "./serverEndpoint";
import type { ShellState } from "./shellState";
import { createOverlayWindow } from "./window";

app.whenReady().then(() => {
  const win = createOverlayWindow();

  // Global show/hide hotkey — the only manual summon/dismiss path. The
  // toggle never steals game focus (showInactive only, AC-2) and a failed
  // registration is logged and non-fatal (AC-3).
  wireGlobalHotkey(app, win);

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
});
