import { beforeEach, describe, expect, it, vi } from "vitest";

// electron is unavailable under vitest; globalShortcut is the only surface
// hotkey.ts touches, so the mock stays that small.
const shortcuts = vi.hoisted(() => ({
  register: vi.fn<(accelerator: string, callback: () => void) => boolean>(),
  unregister: vi.fn(),
  unregisterAll: vi.fn(),
}));
vi.mock("electron", () => ({ globalShortcut: shortcuts }));

import {
  DEFAULT_HOTKEY,
  createVisibilityToggle,
  registerHotkey,
  resolveHotkeyAccelerator,
  wireGlobalHotkey,
} from "../src/hotkey";

/** Fake BrowserWindow; show/focus spies prove the hotkey path never steals focus. */
function fakeWindow(initiallyVisible: boolean) {
  let visible = initiallyVisible;
  return {
    isVisible: vi.fn(() => visible),
    showInactive: vi.fn(() => {
      visible = true;
    }),
    hide: vi.fn(() => {
      visible = false;
    }),
    show: vi.fn(),
    focus: vi.fn(),
  };
}

function fakeApp() {
  const listeners = new Map<string, () => void>();
  return {
    listeners,
    on(event: "will-quit", listener: () => void) {
      listeners.set(event, listener);
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  shortcuts.register.mockReturnValue(true);
});

describe("accelerator resolution", () => {
  it("defaults to CommandOrControl+Alt+D", () => {
    expect(DEFAULT_HOTKEY).toBe("CommandOrControl+Alt+D");
    expect(resolveHotkeyAccelerator({})).toBe(DEFAULT_HOTKEY);
  });

  it("honours the OVERLAY_HOTKEY override", () => {
    expect(resolveHotkeyAccelerator({ OVERLAY_HOTKEY: "CommandOrControl+Shift+K" })).toBe(
      "CommandOrControl+Shift+K",
    );
    expect(resolveHotkeyAccelerator({ OVERLAY_HOTKEY: "  " })).toBe(DEFAULT_HOTKEY);
  });
});

describe("visibility toggle", () => {
  it("shows a hidden overlay with showInactive — never show() or focus()", () => {
    const win = fakeWindow(false);
    createVisibilityToggle(win)();
    expect(win.showInactive).toHaveBeenCalledOnce();
    expect(win.hide).not.toHaveBeenCalled();
    expect(win.show).not.toHaveBeenCalled();
    expect(win.focus).not.toHaveBeenCalled();
  });

  it("hides a visible overlay", () => {
    const win = fakeWindow(true);
    createVisibilityToggle(win)();
    expect(win.hide).toHaveBeenCalledOnce();
    expect(win.showInactive).not.toHaveBeenCalled();
    expect(win.show).not.toHaveBeenCalled();
    expect(win.focus).not.toHaveBeenCalled();
  });
});

describe("global hotkey wiring", () => {
  it("registers the resolved accelerator and routes presses to the toggle", () => {
    const win = fakeWindow(false);
    wireGlobalHotkey(fakeApp(), win, { OVERLAY_HOTKEY: "F9" });

    expect(shortcuts.register).toHaveBeenCalledOnce();
    expect(shortcuts.register.mock.calls[0][0]).toBe("F9");

    const press = shortcuts.register.mock.calls[0][1];
    press();
    expect(win.showInactive).toHaveBeenCalledOnce();
    press();
    expect(win.hide).toHaveBeenCalledOnce();
    expect(win.show).not.toHaveBeenCalled();
    expect(win.focus).not.toHaveBeenCalled();
  });

  it("treats a failed registration as logged and non-fatal — the app still wires up", () => {
    shortcuts.register.mockReturnValue(false);
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const app = fakeApp();

    expect(() => wireGlobalHotkey(app, fakeWindow(false))).not.toThrow();
    expect(error).toHaveBeenCalledWith(
      expect.stringContaining('failed to register hotkey "CommandOrControl+Alt+D"'),
    );
    // Execution continued past the failure: will-quit is still wired.
    expect(app.listeners.has("will-quit")).toBe(true);
    error.mockRestore();
  });

  it("registerHotkey's returned unregister releases only its own accelerator", () => {
    const release = registerHotkey("F10", () => {});
    release();
    expect(shortcuts.unregister).toHaveBeenCalledWith("F10");
  });

  it("unregisters all shortcuts on will-quit", () => {
    const app = fakeApp();
    wireGlobalHotkey(app, fakeWindow(false));

    const onQuit = app.listeners.get("will-quit");
    expect(onQuit).toBeDefined();
    onQuit!();
    expect(shortcuts.unregisterAll).toHaveBeenCalledOnce();
  });
});
