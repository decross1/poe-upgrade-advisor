/**
 * Preload bridge — the renderer's entire capability surface. contextIsolation
 * is on, nodeIntegration off: the card UI can only RECEIVE shell states and
 * ASK to open a details link. It has no network, no clipboard, no node.
 */
import { contextBridge, ipcRenderer } from "electron";
import type { ShellState } from "./shellState";

export interface PoeOverlayBridge {
  onState: (callback: (state: ShellState) => void) => void;
  openDetails: (href: string) => void;
}

const bridge: PoeOverlayBridge = {
  onState: (callback) => {
    ipcRenderer.on("overlay:state", (_event, state: ShellState) => callback(state));
  },
  openDetails: (href) => {
    ipcRenderer.send("overlay:open-details", href);
  },
};

contextBridge.exposeInMainWorld("poeOverlay", bridge);
