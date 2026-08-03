import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createClipboardWatcher,
  isPoeItemText,
  type ClipboardWatcher,
} from "../src/clipboardWatcher";

const ITEM_TEXT =
  "Item Class: Wands\r\nRarity: Rare\r\nDoom Branch\r\nProphecy Wand\r\n--------\r\n";

const watchers: ClipboardWatcher[] = [];
afterEach(() => {
  for (const watcher of watchers.splice(0)) watcher.stop();
});

describe("isPoeItemText — recognition only", () => {
  it.each([
    ITEM_TEXT,
    "Item Class: Currency\nRarity: Currency\nChaos Orb\n",
    "\uFEFFItem Class: Rings\r\nRarity: Unique\r\nThe Taming\r\n",
  ])("accepts the PoE Item Class + Rarity header", (text) => {
    expect(isPoeItemText(text)).toBe(true);
  });

  it.each([
    "",
    "ordinary clipboard notes",
    "Rarity: Rare\nDoom Branch\nProphecy Wand\n",
    "Item Class: Wands\nDoom Branch\nRarity: Rare\n",
    " Item Class: Wands\nRarity: Rare\n",
    "Item Class:\nRarity: Rare\n",
    "Item Class: Wands\nRarity:\n",
  ])("rejects non-item clipboard content without parsing it", (text) => {
    expect(isPoeItemText(text)).toBe(false);
  });
});

describe("clipboard watcher — changed items only", () => {
  it("baselines existing content, emits each changed item once, and ignores non-items", async () => {
    const clipboard = { text: "notes", readText: () => clipboard.text };
    const onItemText = vi.fn();
    const watcher = createClipboardWatcher({ clipboard, onItemText, pollMs: 60_000 });
    watchers.push(watcher);
    watcher.start();

    await watcher.pollNow();
    clipboard.text = "still notes";
    await watcher.pollNow();
    expect(onItemText).not.toHaveBeenCalled();

    clipboard.text = ITEM_TEXT;
    await watcher.pollNow();
    await watcher.pollNow();
    expect(onItemText).toHaveBeenCalledTimes(1);
    expect(onItemText).toHaveBeenLastCalledWith(ITEM_TEXT);

    // Copying something else and then this item again is a second explicit
    // clipboard change, so it produces exactly one second capture.
    clipboard.text = "trade message";
    await watcher.pollNow();
    clipboard.text = ITEM_TEXT;
    await watcher.pollNow();
    expect(onItemText).toHaveBeenCalledTimes(2);
  });

  it("silently retries after a transient clipboard read failure", async () => {
    const clipboard = {
      text: "notes",
      fail: false,
      readText() {
        if (this.fail) throw new Error("clipboard locked");
        return this.text;
      },
    };
    const onItemText = vi.fn();
    const watcher = createClipboardWatcher({ clipboard, onItemText, pollMs: 60_000 });
    watchers.push(watcher);
    watcher.start();

    clipboard.fail = true;
    await expect(watcher.pollNow()).resolves.toBeUndefined();
    clipboard.fail = false;
    clipboard.text = ITEM_TEXT;
    await watcher.pollNow();

    expect(onItemText).toHaveBeenCalledOnce();
  });
});
