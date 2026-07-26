/**
 * S1: the clipboard — populated by the game's OWN Ctrl+C — is the only input
 * this process ever takes from the game. Read-only, and only ever called from
 * the explicit hotkey path (S2: one server action per keypress; no watchers,
 * no polling). We never synthesize input into the game and never inspect the
 * game process.
 */
import { clipboard } from "electron";

export function readItemText(): string {
  return clipboard.readText();
}
