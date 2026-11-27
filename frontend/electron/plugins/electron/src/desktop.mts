import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import {
  app,
  BrowserWindow,
  Menu,
  Notification,
  nativeImage,
  powerMonitor,
  session,
  shell,
  Tray,
} from "./app.mjs";

/** What the platform hands a plugin: the way to tell the page something. */
interface Context {
  notifyListeners: (eventName: string, data?: unknown) => void;
}

/** Matches electron-builder's `appId`, which names the app to Windows. */
const APP_ID = "studio.beyonders.initiative";

/** Passed when the computer opens the app at sign-in, to start in the tray. */
const HIDDEN = "--hidden";

/**
 * Passed by the Quit item on the Windows taskbar button, which starts the app
 * again: the copy already running hears it and quits.
 */
const QUIT = "--quit";

/**
 * How often the computer is asked how long it has gone without input. Input
 * since the last asking is the person at the computer, in this app or any
 * other, and the page reports it as the browser reports a click.
 */
const COMPUTER_POLL_MS = 30_000;

/** The session vendor pages open in: apart from the app's own, and kept, so the
 *  person stays signed in at the vendor from one connection to the next. */
const VENDOR_PARTITION = "persist:vendor-pages";

/** A vendor page open now, where its flow comes back to, and the address it
 *  came back with. */
interface VendorPage {
  window: InstanceType<typeof BrowserWindow>;
  returnPath: string;
  returned: string | null;
}

/** The tray menu's words, in the person's language; the page sends them. */
interface TrayMenu {
  open: string;
  quit: string;
}

/**
 * The desktop app's own shell: system notifications, the unread badge, and
 * staying in the tray when the window closes. Windows and Linux keep running
 * in the tray while the person wants them to; a Mac keeps running in the dock,
 * as Mac apps do. It also tells the page when the person is at the computer,
 * which a browser tab can only tell from input to itself, and opens a plug-in
 * connection's vendor page in a window of its own (`openVendorPage`).
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
      "openVendorPage",
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
  private vendorPage: VendorPage | null = null;

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
    app.on("second-instance", (_event, argv) => {
      if (argv.includes(QUIT)) {
        app.quit();
      }
    });
    app.on("browser-window-created", (_event, window) => {
      window.on("close", (event) => {
        if (this.quitting || !isMainWindow(window) || !this.staysOpen()) {
          return;
        }
        event.preventDefault();
        window.hide();
      });
    });
    this.watchComputer();
    // A vendor page's flow comes back to the server's own address, which is
    // taken here rather than loaded (`openVendorPage`).
    session.fromPartition(VENDOR_PARTITION).webRequest.onBeforeRequest((details, callback) => {
      const page = this.vendorPage;
      if (page && details.resourceType === "mainFrame" && pathOf(details.url) === page.returnPath) {
        page.returned = details.url;
        callback({ cancel: true });
        page.window.close();
        return;
      }
      callback({});
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

  /**
   * Name the tray menu's items, which puts the tray up where there is one. On
   * Windows, Quit also goes on the taskbar button's menu, beside its own Close
   * window, which only hides the window while the tray is up.
   */
  async setTray(menu: TrayMenu) {
    this.menu = menu;
    if (process.platform === "win32") {
      app.setUserTasks([
        {
          program: process.execPath,
          arguments: QUIT,
          title: menu.quit,
          description: menu.quit,
          iconPath: process.execPath,
          iconIndex: 0,
        },
      ]);
    }
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

  /**
   * Open a plug-in connection's vendor page in a window over the app's, in a
   * session of its own, until its flow comes back to `returnPath`: that
   * address is taken rather than loaded, the window closes, and it is
   * answered. Closing the window answers null. One at a time; a new one
   * closes the last. Links the vendor opens in a new window go to the
   * browser.
   */
  async openVendorPage({
    url,
    returnPath,
  }: {
    url: string;
    returnPath: string;
  }): Promise<{ returned: string | null }> {
    const parent = mainWindow();
    if (!parent || !isWebAddress(url) || !returnPath.startsWith("/")) {
      return { returned: null };
    }
    this.vendorPage?.window.close();
    const window = new BrowserWindow({
      parent,
      width: 960,
      height: 760,
      autoHideMenuBar: true,
      webPreferences: { partition: VENDOR_PARTITION, sandbox: true },
    });
    const page: VendorPage = { window, returnPath, returned: null };
    this.vendorPage = page;
    window.webContents.setWindowOpenHandler(({ url: target }) => {
      if (isWebAddress(target)) {
        void shell.openExternal(target);
      }
      return { action: "deny" };
    });
    return new Promise((resolve) => {
      window.on("closed", () => {
        if (this.vendorPage === page) {
          this.vendorPage = null;
        }
        resolve({ returned: page.returned });
      });
      window.loadURL(url).catch(() => undefined);
    });
  }

  /**
   * Say "computerActive" whenever the computer saw input since it was last
   * asked. A computer that cannot tell reports no time without input at all,
   * which would read as someone always there, so its readings count only once
   * one has shown it going quiet; until then the page's own input is the sign.
   */
  private watchComputer() {
    let readable = false;
    setInterval(() => {
      if (powerMonitor.getSystemIdleTime() * 1000 >= COMPUTER_POLL_MS) {
        readable = true;
      } else if (readable) {
        this.context.notifyListeners("computerActive");
      }
    }, COMPUTER_POLL_MS);
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

/** The app's own window, as opposed to the splash screen, which is a file, and
 *  the vendor pages it opens over itself. */
const isMainWindow = (window: InstanceType<typeof BrowserWindow>) =>
  !window.getParentWindow() && !window.webContents.getURL().startsWith("file:");

const isWebAddress = (address: string) => {
  try {
    const { protocol } = new URL(address);
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
};

const pathOf = (address: string) => {
  try {
    return new URL(address).pathname;
  } catch {
    return null;
  }
};

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
