/**
 * Preload bridge — the renderer's entire capability surface. contextIsolation
 * is on, nodeIntegration off: the card UI can only RECEIVE shell states,
 * ASK to open a details link, and FORWARD a chip tap. It has no network, no
 * clipboard, no node — the /diff a tap may cause is issued solely by the
 * main-process flow (S2: one tap = at most one server action).
 */
import { contextBridge, ipcRenderer } from "electron";
import type { Assumption } from "../../web/src/lib/overrides";
import type { ShellState } from "./shellState";

export interface PoeOverlayBridge {
  onState: (callback: (state: ShellState) => void) => void;
  openDetails: (href: string) => void;
  /** I3: forward a chip tap to the main-process flow (§7 re-diff). */
  tapChip: (assumption: Assumption) => void;
}

const bridge: PoeOverlayBridge = {
  onState: (callback) => {
    ipcRenderer.on("overlay:state", (_event, state: ShellState) => callback(state));
  },
  openDetails: (href) => {
    ipcRenderer.send("overlay:open-details", href);
  },
  tapChip: (assumption) => {
    ipcRenderer.send("overlay:chip-tap", assumption);
  },
};

contextBridge.exposeInMainWorld("poeOverlay", bridge);
