/**
 * S1: the clipboard — populated by the game's OWN Ctrl+C — is the only input
 * this process ever takes from the game. Read-only. We never synthesize input
 * into the game and never inspect the game process.
 */
import { clipboard } from "electron";
import type { ClipboardSource } from "./clipboardWatcher";

export const electronClipboardSource: ClipboardSource = {
  readText: () => clipboard.readText(),
};
