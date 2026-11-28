/**
 * The desktop app's shell: what closing the window does, what a notification
 * click hands back, what the computer is told about opening at sign-in, when
 * the page hears that the person is at the computer, and the window a vendor
 * page opens in.
 */
import type { EventEmitter } from "node:events";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { FakeWindow, FakeVendorWindow, FakeNotification, Emitter } = vi.hoisted(() => {
  // Hoisted above the imports, so Node's own module is fetched directly.
  const Emitter = process.getBuiltinModule("node:events").EventEmitter;
  class FakeWindow extends Emitter {
    url = "capacitor://studio.beyonders.initiative/";
    webContents = { getURL: () => this.url };
    getParentWindow = () => null;
    hide = vi.fn();
    show = vi.fn();
    focus = vi.fn();
    restore = vi.fn();
    isMinimized = () => false;
    setOverlayIcon = vi.fn();
    setTitleBarOverlay = vi.fn();
  }

  /** A window the app opens over its own. */
  class FakeVendorWindow extends Emitter {
    static made: FakeVendorWindow[] = [];
    openHandler: ((details: { url: string }) => { action: string }) | null = null;
    webContents = {
      getURL: () => "https://github.test/",
      setWindowOpenHandler: (handler: (details: { url: string }) => { action: string }) => {
        this.openHandler = handler;
      },
    };
    loadURL = vi.fn(async (_url: string) => undefined);
    close = vi.fn(() => this.emit("closed"));
    constructor(readonly options: { parent: unknown }) {
      super();
      FakeVendorWindow.made.push(this);
    }
    getParentWindow = () => this.options.parent;
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
  return { FakeWindow, FakeVendorWindow, FakeNotification, Emitter };
});
type FakeWindow = InstanceType<typeof FakeWindow>;
type FakeVendorWindow = InstanceType<typeof FakeVendorWindow>;
type RequestListener = (
  details: { url: string; resourceType: string },
  callback: (response: { cancel?: boolean }) => void
) => void;

const electron = vi.hoisted(() => ({
  windows: [] as unknown[],
  userData: "",
  /** Seconds the computer has gone without input. */
  idle: 0,
  /** What the vendor pages' session does with each request. */
  vendorRequests: null as RequestListener | null,
  partition: "",
  openedExternally: [] as string[],
  app: null as unknown as EventEmitter & Record<string, ReturnType<typeof vi.fn>>,
}));

vi.mock("./app.mjs", () => {
  const app = Object.assign(new Emitter(), {
    setAppUserModelId: vi.fn(),
    setBadgeCount: vi.fn(),
    getPath: () => electron.userData,
    getAppPath: () => "/app",
    isPackaged: false,
    getLoginItemSettings: vi.fn(() => ({ openAtLogin: false })),
    setLoginItemSettings: vi.fn(),
    setUserTasks: vi.fn(),
    quit: vi.fn(),
  });
  electron.app = app as never;
  return {
    app,
    BrowserWindow: Object.assign(FakeVendorWindow, { getAllWindows: () => electron.windows }),
    session: {
      fromPartition: (name: string) => {
        electron.partition = name;
        return {
          webRequest: {
            onBeforeRequest: (listener: RequestListener) => {
              electron.vendorRequests = listener;
            },
          },
        };
      },
    },
    shell: {
      openExternal: async (url: string) => {
        electron.openedExternally.push(url);
      },
    },
    Menu: { buildFromTemplate: (template: unknown) => template },
    Notification: FakeNotification,
    powerMonitor: { getSystemIdleTime: () => electron.idle },
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
  electron.openedExternally = [];
  FakeVendorWindow.made = [];
  vi.stubEnv("XDG_CONFIG_HOME", mkdtempSync(join(tmpdir(), "initiative-xdg-")));
  FakeNotification.made = [];
  vi.clearAllMocks();
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

describe("the taskbar's Quit item", () => {
  it("goes on the Windows taskbar button's menu, in the page's words", async () => {
    onPlatform("win32");
    const { desktop } = started();

    await desktop.setTray({ open: "Open Initiative", quit: "Quit Initiative" });
    expect(electron.app.setUserTasks).toHaveBeenCalledWith([
      expect.objectContaining({ arguments: "--quit", title: "Quit Initiative" }),
    ]);
  });

  it("is Windows' alone", async () => {
    onPlatform("linux");
    const { desktop } = started();

    await desktop.setTray({ open: "Open", quit: "Quit" });
    expect(electron.app.setUserTasks).not.toHaveBeenCalled();
  });

  it("quits the copy already running, past the tray", async () => {
    onPlatform("win32");
    const { desktop, window } = started();
    await desktop.setTray({ open: "Open", quit: "Quit" });

    electron.app.emit("second-instance", {}, [process.execPath, "--hidden"]);
    expect(electron.app.quit).not.toHaveBeenCalled();

    electron.app.emit("second-instance", {}, [process.execPath, "--quit"]);
    expect(electron.app.quit).toHaveBeenCalled();
    electron.app.emit("before-quit");
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

  it("is on from the first start until the person switches it off", async () => {
    onPlatform("linux");
    electron.app.isPackaged = true as never;
    try {
      const { desktop } = started();
      expect(readFileSync(autostart(), "utf8")).toContain("--hidden");

      await desktop.setOpenAtLogin({ enabled: false });
      const next = new Desktop({ notifyListeners: vi.fn() });
      next.load();
      await expect(next.getSettings()).resolves.toMatchObject({ openAtLogin: false });
    } finally {
      electron.app.isPackaged = false as never;
    }
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

describe("the person at the computer", () => {
  it("is reported once the computer has shown it can tell", () => {
    vi.useFakeTimers();
    electron.idle = 0;
    const { notifyListeners } = started();
    // Nothing but zeroes is also what a computer that cannot tell says.
    vi.advanceTimersByTime(60_000);
    expect(notifyListeners).not.toHaveBeenCalledWith("computerActive");

    electron.idle = 45;
    vi.advanceTimersByTime(30_000);
    expect(notifyListeners).not.toHaveBeenCalledWith("computerActive");

    // Typing in another app since the last asking.
    electron.idle = 4;
    vi.advanceTimersByTime(30_000);
    expect(notifyListeners).toHaveBeenCalledWith("computerActive");
    vi.useRealTimers();
  });
});

describe("a vendor page", () => {
  const RETURN = "/api/v1/plugin-connections/handback";

  /** What the vendor pages' session answers one request. */
  const request = (url: string, resourceType = "mainFrame") => {
    let answer: { cancel?: boolean } | undefined;
    electron.vendorRequests?.({ url, resourceType }, (response) => {
      answer = response;
    });
    return answer;
  };

  const opened = (desktop: Desktop) => {
    const answer = desktop.openVendorPage({
      url: "https://github.test/login/oauth/authorize?state=s",
      returnPath: RETURN,
    });
    return { answer, page: FakeVendorWindow.made.at(-1) as FakeVendorWindow };
  };

  it("opens over the app in a session of its own, and takes its flow's return", async () => {
    const { desktop, window } = started();
    const { answer, page } = opened(desktop);

    expect(page.options).toMatchObject({
      parent: window,
      webPreferences: { partition: "persist:vendor-pages", sandbox: true },
    });
    expect(electron.partition).toBe("persist:vendor-pages");
    expect(page.loadURL).toHaveBeenCalledWith("https://github.test/login/oauth/authorize?state=s");
    // The server's own callback loads; the address it sends the flow back to does not.
    expect(request("https://server.test/api/v1/plugin-connections/callback?code=c")).toEqual({});
    expect(request(`https://server.test${RETURN}?code=h`, "image")).toEqual({});
    expect(request(`https://server.test${RETURN}?code=h`)).toEqual({ cancel: true });

    await expect(answer).resolves.toEqual({ returned: `https://server.test${RETURN}?code=h` });
    expect(page.close).toHaveBeenCalled();
  });

  it("answers nothing when the person closes it, or a newer one replaces it", async () => {
    const { desktop } = started();
    const first = opened(desktop);
    const second = opened(desktop);
    await expect(first.answer).resolves.toEqual({ returned: null });

    second.page.close();
    await expect(second.answer).resolves.toEqual({ returned: null });
    expect(request(`https://server.test${RETURN}?code=h`)).toEqual({});
  });

  it("sends a window the vendor opens to the browser", () => {
    const { desktop } = started();
    const { page } = opened(desktop);

    expect(page.openHandler?.({ url: "https://docs.github.test/" })).toEqual({ action: "deny" });
    expect(page.openHandler?.({ url: "file:///etc/passwd" })).toEqual({ action: "deny" });
    expect(electron.openedExternally).toEqual(["https://docs.github.test/"]);
  });

  it("closes rather than hiding in the tray, as the app's own window does", async () => {
    onPlatform("win32");
    const { desktop } = started();
    await desktop.setTray({ open: "Open", quit: "Quit" });
    const { page } = opened(desktop);
    electron.app.emit("browser-window-created", {}, page);

    expect(close(page as unknown as FakeWindow)).toBe(false);
  });

  it("opens nothing for an address that is not a web page", async () => {
    const { desktop } = started();

    await expect(
      desktop.openVendorPage({ url: "file:///etc/passwd", returnPath: RETURN })
    ).resolves.toEqual({ returned: null });
    expect(FakeVendorWindow.made).toEqual([]);
  });
});
