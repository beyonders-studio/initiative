import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { app, BrowserWindow, Menu, Notification, nativeImage, Tray } from "./app.mjs";

/** What the platform hands a plugin: the way to tell the page something. */
interface Context {
  notifyListeners: (eventName: string, data?: unknown) => void;
}

/** Matches electron-builder's `appId`, which names the app to Windows. */
const APP_ID = "studio.beyonders.initiative";

/** Passed when the computer opens the app at sign-in, to start in the tray. */
const HIDDEN = "--hidden";

/** The tray menu's words, in the person's language; the page sends them. */
interface TrayMenu {
  open: string;
  quit: string;
}

/**
 * The desktop app's own shell: system notifications, the unread badge, and
 * staying in the tray when the window closes. Windows and Linux keep running
 * in the tray while the person wants them to; a Mac keeps running in the dock,
 * as Mac apps do.
 */
export class Desktop {
  static __capacitorElectronPlugin = {
    name: "Desktop",
    methods: [
      "notify",
      "setBadge",
      "setTray",
      "getSettings",
      "setKeepRunning",
      "setOpenAtLogin",
      "setTitleBarColors",
    ],
  };

  private tray: InstanceType<typeof Tray> | null = null;
  private quitting = false;
  private keepRunning = true;
  /** Sent by the page as soon as it loads, signed in or not; the tray waits for it. */
  private menu: TrayMenu | null = null;
  private tooltip = "Initiative";
  /** Shown notifications, held until they are clicked or dismissed. */
  private readonly shown = new Set<InstanceType<typeof Notification>>();

  constructor(private readonly context: Context) {}

  load() {
    if (process.platform === "win32") {
      app.setAppUserModelId(APP_ID);
    }
    const settings = readSettings();
    this.keepRunning = settings.keepRunning !== false;
    // On by default: the first packaged start turns it on, once. After that
    // it is the person's to change.
    if (settings.openAtLogin === undefined && app.isPackaged) {
      this.setOpenAtLogin({ enabled: true });
    }
    app.on("before-quit", () => {
      this.quitting = true;
    });
    app.on("activate", () => this.show());
    app.on("browser-window-created", (_event, window) => {
      window.on("close", (event) => {
        if (this.quitting || !isMainWindow(window) || !this.staysOpen()) {
          return;
        }
        event.preventDefault();
        window.hide();
      });
    });
  }

  /** Show one notification. Clicking it brings the window back and hands the page `tag`. */
  async notify({ title, body, tag }: { title: string; body?: string; tag: string }) {
    if (!Notification.isSupported()) {
      return;
    }
    const notification = new Notification({ title, body: body ?? "" });
    this.shown.add(notification);
    notification.on("click", () => {
      this.shown.delete(notification);
      this.show();
      this.context.notifyListeners("notificationClicked", { tag });
    });
    notification.on("close", () => this.shown.delete(notification));
    notification.show();
  }

  /**
   * The unread count on the dock, the launcher and the tray. Windows shows it
   * as an overlay on the taskbar button, drawn by the page as `overlay`.
   */
  async setBadge({
    count,
    overlay,
    tooltip,
  }: {
    count: number;
    overlay?: string;
    tooltip: string;
  }) {
    this.tooltip = tooltip;
    app.setBadgeCount(count);
    const window = mainWindow();
    if (process.platform === "win32" && window) {
      window.setOverlayIcon(
        count > 0 && overlay ? nativeImage.createFromDataURL(overlay) : null,
        tooltip
      );
    }
    this.refreshTray();
  }

  /** Name the tray menu's items, which puts the tray up where there is one. */
  async setTray(menu: TrayMenu) {
    this.menu = menu;
    this.refreshTray();
  }

  async getSettings() {
    return {
      // Only Windows and Linux close to the tray; a Mac always keeps running.
      tray: hasTray(),
      keepRunning: this.keepRunning,
      openAtLogin: openAtLogin(),
    };
  }

  async setKeepRunning({ enabled }: { enabled: boolean }) {
    this.keepRunning = enabled;
    writeSettings({ keepRunning: enabled });
    this.refreshTray();
    // The app opens at sign-in in the tray only while there is a tray to open in.
    if (openAtLogin()) {
      setOpenAtLogin(true, this.startsHidden());
    }
  }

  async setOpenAtLogin({ enabled }: { enabled: boolean }) {
    setOpenAtLogin(enabled, this.startsHidden());
    writeSettings({ openAtLogin: enabled });
  }

  /**
   * Colour the window's own buttons, which Windows and Linux draw over the
   * end of the page's title bar, to match it. A Mac draws its buttons the
   * same in any theme.
   */
  async setTitleBarColors({ color, symbolColor }: { color: string; symbolColor: string }) {
    if (process.platform === "darwin") {
      return;
    }
    mainWindow()?.setTitleBarOverlay({ color, symbolColor });
  }

  /** Closing hides the window only where there is a way back: the dock, or the tray. */
  private staysOpen() {
    return process.platform === "darwin" || this.tray !== null;
  }

  private startsHidden() {
    return hasTray() && this.keepRunning;
  }

  private show() {
    const window = mainWindow();
    if (!window) {
      return;
    }
    if (window.isMinimized()) {
      window.restore();
    }
    window.show();
    window.focus();
  }

  private refreshTray() {
    const menu = this.menu;
    if (!(hasTray() && this.keepRunning && menu)) {
      this.tray?.destroy();
      this.tray = null;
      return;
    }
    if (!this.tray) {
      const size = process.platform === "win32" ? 16 : 22;
      const icon = nativeImage
        .createFromPath(join(app.getAppPath(), "assets", "icon.png"))
        .resize({ width: size, height: size });
      this.tray = new Tray(icon);
      this.tray.on("click", () => this.show());
    }
    this.tray.setToolTip(this.tooltip);
    this.tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: menu.open, click: () => this.show() },
        { type: "separator" },
        { label: menu.quit, click: () => app.quit() },
      ])
    );
  }
}

const hasTray = () => process.platform === "win32" || process.platform === "linux";

/** The app's own window, as opposed to the splash screen, which is a file. */
const isMainWindow = (window: InstanceType<typeof BrowserWindow>) =>
  !window.webContents.getURL().startsWith("file:");

export const mainWindow = () => BrowserWindow.getAllWindows().find(isMainWindow) ?? null;

// --- Settings kept on this computer -------------------------------------------

const settingsFile = () => join(app.getPath("userData"), "desktop.json");

/** What the person chose; a setting they never touched is absent. */
interface Settings {
  keepRunning?: boolean;
  openAtLogin?: boolean;
}

const readSettings = (): Settings => {
  try {
    return JSON.parse(readFileSync(settingsFile(), "utf8"));
  } catch {
    return {};
  }
};

const writeSettings = (change: Settings) => {
  writeFileSync(settingsFile(), JSON.stringify({ ...readSettings(), ...change }));
};

// --- Opening at sign-in -----------------------------------------------------
// Windows and macOS keep a login item for the app. Linux has none, so the app
// writes an autostart entry of its own, as the desktop specification describes.

const autostartFile = () =>
  join(
    process.env.XDG_CONFIG_HOME || join(homedir(), ".config"),
    "autostart",
    "initiative.desktop"
  );

const openAtLogin = (): boolean => {
  if (process.platform === "linux") {
    try {
      readFileSync(autostartFile());
      return true;
    } catch {
      return false;
    }
  }
  return app.getLoginItemSettings().openAtLogin;
};

const setOpenAtLogin = (enabled: boolean, hidden: boolean) => {
  if (process.platform !== "linux") {
    app.setLoginItemSettings({ openAtLogin: enabled, args: hidden ? [HIDDEN] : [] });
    return;
  }
  const file = autostartFile();
  if (!enabled) {
    rmSync(file, { force: true });
    return;
  }
  mkdirSync(join(file, ".."), { recursive: true });
  const exec = `"${process.execPath}"${hidden ? ` ${HIDDEN}` : ""}`;
  writeFileSync(
    file,
    ["[Desktop Entry]", "Type=Application", "Name=Initiative", `Exec=${exec}`, ""].join("\n")
  );
};
