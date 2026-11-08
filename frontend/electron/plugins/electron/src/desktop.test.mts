/**
 * The desktop app's shell: what closing the window does, what a notification
 * click hands back, and what the computer is told about opening at sign-in.
 */
import type { EventEmitter } from "node:events";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { FakeWindow, FakeNotification, Emitter } = vi.hoisted(() => {
  // Hoisted above the imports, so Node's own module is fetched directly.
  const Emitter = process.getBuiltinModule("node:events").EventEmitter;
  class FakeWindow extends Emitter {
    url = "capacitor://studio.beyonders.initiative/";
    webContents = { getURL: () => this.url };
    hide = vi.fn();
    show = vi.fn();
    focus = vi.fn();
    restore = vi.fn();
    isMinimized = () => false;
    setOverlayIcon = vi.fn();
    setTitleBarOverlay = vi.fn();
  }

  class FakeNotification extends Emitter {
    static isSupported = () => true;
    static made: FakeNotification[] = [];
    show = vi.fn();
    constructor(readonly options: { title: string; body: string }) {
      super();
      FakeNotification.made.push(this);
    }
  }
  return { FakeWindow, FakeNotification, Emitter };
});
type FakeWindow = InstanceType<typeof FakeWindow>;

const electron = vi.hoisted(() => ({
  windows: [] as unknown[],
  userData: "",
  app: null as unknown as EventEmitter & Record<string, ReturnType<typeof vi.fn>>,
}));

vi.mock("./app.mjs", () => {
  const app = Object.assign(new Emitter(), {
    setAppUserModelId: vi.fn(),
    setBadgeCount: vi.fn(),
    getPath: () => electron.userData,
    getAppPath: () => "/app",
    getLoginItemSettings: vi.fn(() => ({ openAtLogin: false })),
    setLoginItemSettings: vi.fn(),
    quit: vi.fn(),
  });
  electron.app = app as never;
  return {
    app,
    BrowserWindow: { getAllWindows: () => electron.windows },
    Menu: { buildFromTemplate: (template: unknown) => template },
    Notification: FakeNotification,
    nativeImage: {
      createFromPath: () => ({ resize: () => ({}) }),
      createFromDataURL: (url: string) => ({ url }),
    },
    Tray: class {
      on = vi.fn();
      setToolTip = vi.fn();
      setContextMenu = vi.fn();
      destroy = vi.fn();
    },
  };
});

import { Desktop } from "./desktop.mjs";

const onPlatform = (platform: NodeJS.Platform) =>
  vi.spyOn(process, "platform", "get").mockReturnValue(platform);

const started = () => {
  const notifyListeners = vi.fn();
  const desktop = new Desktop({ notifyListeners });
  desktop.load();
  const window = new FakeWindow();
  electron.windows = [window];
  electron.app.emit("browser-window-created", {}, window);
  return { desktop, window, notifyListeners };
};

/** Close the window as its close button would, and say whether it stayed. */
const close = (window: FakeWindow) => {
  const event = { preventDefault: vi.fn() };
  window.emit("close", event);
  return event.preventDefault.mock.calls.length > 0;
};

beforeEach(() => {
  electron.userData = mkdtempSync(join(tmpdir(), "initiative-desktop-"));
  vi.stubEnv("XDG_CONFIG_HOME", mkdtempSync(join(tmpdir(), "initiative-xdg-")));
  FakeNotification.made = [];
});

afterEach(() => {
  electron.app.removeAllListeners();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("closing the window", () => {
  it("leaves the app in the tray until the person says otherwise", async () => {
    onPlatform("win32");
    const { desktop, window } = started();
    // Before the page has named the tray's menu there is no tray to wait in.
    expect(close(window)).toBe(false);

    await desktop.setTray({ open: "Open", quit: "Quit" });
    expect(close(window)).toBe(true);
    expect(window.hide).toHaveBeenCalled();

    await desktop.setKeepRunning({ enabled: false });
    expect(close(window)).toBe(false);
    // Kept on this computer for the next start.
    const next = new Desktop({ notifyListeners: vi.fn() });
    next.load();
    await expect(next.getSettings()).resolves.toMatchObject({ keepRunning: false });
  });

  it("always keeps a Mac app running, as Mac apps do", async () => {
    onPlatform("darwin");
    const { desktop, window } = started();
    await desktop.setKeepRunning({ enabled: false });

    expect(close(window)).toBe(true);
    await expect(desktop.getSettings()).resolves.toMatchObject({ tray: false });
  });

  it("lets the app go when it is quitting", () => {
    onPlatform("linux");
    const { window } = started();
    electron.app.emit("before-quit");

    expect(close(window)).toBe(false);
  });

  it("leaves the splash screen to close", () => {
    onPlatform("linux");
    const { window } = started();
    window.url = "file:///app/assets/splash.html";

    expect(close(window)).toBe(false);
  });
});

describe("a notification", () => {
  it("brings the window back and hands the page its tag when clicked", async () => {
    onPlatform("linux");
    const { desktop, window, notifyListeners } = started();

    await desktop.notify({ title: "Ana mentioned you", tag: "42" });
    const [shown] = FakeNotification.made;
    expect(shown.show).toHaveBeenCalled();
    shown.emit("click");

    expect(window.show).toHaveBeenCalled();
    expect(notifyListeners).toHaveBeenCalledWith("notificationClicked", { tag: "42" });
  });
});

describe("the badge", () => {
  const tooltip = "Initiative: 3 unread";

  it("is the count on the dock and launcher, and an overlay on Windows", async () => {
    onPlatform("win32");
    const { desktop, window } = started();

    await desktop.setBadge({ count: 3, overlay: "data:image/png;base64,AA", tooltip });
    expect(electron.app.setBadgeCount).toHaveBeenCalledWith(3);
    expect(window.setOverlayIcon).toHaveBeenCalledWith(
      { url: "data:image/png;base64,AA" },
      tooltip
    );

    await desktop.setBadge({ count: 0, tooltip });
    expect(window.setOverlayIcon).toHaveBeenLastCalledWith(null, tooltip);
  });
});

describe("the title bar's window buttons", () => {
  const colors = { color: "#f8fafc", symbolColor: "#020618" };

  it("take the page's colours on Windows and Linux", async () => {
    onPlatform("linux");
    const { desktop, window } = started();

    await desktop.setTitleBarColors(colors);
    expect(window.setTitleBarOverlay).toHaveBeenCalledWith(colors);
  });

  it("are left alone on a Mac", async () => {
    onPlatform("darwin");
    const { desktop, window } = started();

    await desktop.setTitleBarColors(colors);
    expect(window.setTitleBarOverlay).not.toHaveBeenCalled();
  });
});

describe("opening at sign-in", () => {
  const autostart = () =>
    join(process.env.XDG_CONFIG_HOME as string, "autostart", "initiative.desktop");

  it("writes a Linux autostart entry that starts in the tray", async () => {
    onPlatform("linux");
    const { desktop } = started();

    await desktop.setOpenAtLogin({ enabled: true });
    expect(readFileSync(autostart(), "utf8")).toContain(`Exec="${process.execPath}" --hidden`);
    await expect(desktop.getSettings()).resolves.toMatchObject({ openAtLogin: true });

    // With no tray to wait in, it opens its window.
    await desktop.setKeepRunning({ enabled: false });
    expect(readFileSync(autostart(), "utf8")).not.toContain("--hidden");

    await desktop.setOpenAtLogin({ enabled: false });
    await expect(desktop.getSettings()).resolves.toMatchObject({ openAtLogin: false });
  });

  it("asks Windows for a login item that starts in the tray", async () => {
    onPlatform("win32");
    const { desktop } = started();

    await desktop.setOpenAtLogin({ enabled: true });
    expect(electron.app.setLoginItemSettings).toHaveBeenCalledWith({
      openAtLogin: true,
      args: ["--hidden"],
    });
  });
});
