/**
 * TASK-210-S4 acceptance: the global hotkey toggles overlay visibility.
 * main.ts is imported for real with the electron module mocked, so the
 * wiring itself is under test: default accelerator + OVERLAY_HOTKEY
 * override, showInactive()-only show path (never show()/focus() — game
 * focus is sacred), non-fatal registration failure, unregisterAll on quit.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const win = {
    isVisible: vi.fn<() => boolean>(() => false),
    showInactive: vi.fn(),
    hide: vi.fn(),
    show: vi.fn(),
    focus: vi.fn(),
    setMenu: vi.fn(),
    loadFile: vi.fn(),
    webContents: { once: vi.fn(), send: vi.fn() },
  };
  return {
    win,
    willQuit: [] as Array<() => void>,
    register: vi.fn((_accelerator: string, _callback: () => void) => true),
    unregisterAll: vi.fn(),
  };
});

vi.mock("electron", () => ({
  app: {
    whenReady: () => Promise.resolve(),
    on: (event: string, handler: () => void) => {
      if (event === "will-quit") mocks.willQuit.push(handler);
    },
  },
  ipcMain: { on: vi.fn() },
  shell: { openExternal: vi.fn() },
  clipboard: { readText: () => "" },
  globalShortcut: {
    register: mocks.register,
    unregister: vi.fn(),
    unregisterAll: mocks.unregisterAll,
  },
  BrowserWindow: vi.fn(() => mocks.win),
}));

/** Re-import main.ts fresh and let whenReady().then(...) fire. */
async function boot(registerOk = true): Promise<void> {
  vi.resetModules();
  mocks.register.mockReset().mockReturnValue(registerOk);
  mocks.unregisterAll.mockReset();
  mocks.win.isVisible.mockReset().mockReturnValue(false);
  mocks.win.showInactive.mockReset();
  mocks.win.hide.mockReset();
  mocks.win.webContents.once.mockReset();
  mocks.willQuit.length = 0;
  await import("../src/main");
  await vi.waitFor(() => expect(mocks.register).toHaveBeenCalled());
}

function registeredToggle(): () => void {
  const callback = mocks.register.mock.calls[0]?.[1];
  if (typeof callback !== "function") throw new Error("no toggle callback registered");
  return callback;
}

afterEach(() => {
  delete process.env.OVERLAY_HOTKEY;
  vi.restoreAllMocks();
});

describe("overlay hotkey wiring", () => {
  it("registers the default accelerator CommandOrControl+Alt+D", async () => {
    await boot();
    expect(mocks.register).toHaveBeenCalledWith("CommandOrControl+Alt+D", expect.any(Function));
  });

  it("OVERLAY_HOTKEY overrides the default accelerator", async () => {
    process.env.OVERLAY_HOTKEY = "CommandOrControl+Shift+K";
    await boot();
    expect(mocks.register).toHaveBeenCalledWith("CommandOrControl+Shift+K", expect.any(Function));
  });

  it("hidden -> shown uses showInactive() and NEVER show()/focus()", async () => {
    await boot();
    mocks.win.isVisible.mockReturnValue(false);
    registeredToggle()();
    expect(mocks.win.showInactive).toHaveBeenCalledTimes(1);
    expect(mocks.win.show).not.toHaveBeenCalled();
    expect(mocks.win.focus).not.toHaveBeenCalled();
    expect(mocks.win.hide).not.toHaveBeenCalled();
  });

  it("shown -> hidden calls hide()", async () => {
    await boot();
    mocks.win.isVisible.mockReturnValue(true);
    registeredToggle()();
    expect(mocks.win.hide).toHaveBeenCalledTimes(1);
    expect(mocks.win.showInactive).not.toHaveBeenCalled();
  });

  it("a failed registration is logged, does not throw, and leaves the app running", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(boot(false)).resolves.toBeUndefined();
    expect(errorSpy).toHaveBeenCalledWith(expect.stringContaining("CommandOrControl+Alt+D"));
    // The clipboard path is unaffected: pipeline.start is still wired to load.
    expect(mocks.win.webContents.once).toHaveBeenCalledWith("did-finish-load", expect.any(Function));
  });

  it("unregisterAll runs on will-quit", async () => {
    await boot();
    expect(mocks.willQuit.length).toBeGreaterThan(0);
    for (const handler of mocks.willQuit) handler();
    expect(mocks.unregisterAll).toHaveBeenCalledTimes(1);
  });
});
