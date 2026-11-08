import { registerPlugin } from "@capacitor/core";

/** The tray menu's words, in the person's language. */
export interface DesktopTrayMenu {
  open: string;
  quit: string;
}

/** The desktop app's own shell (`frontend/electron/plugins`). */
export interface DesktopPlugin {
  /** Show a system notification; clicking it reports `tag` back. */
  notify(options: { title: string; body?: string; tag: string }): Promise<void>;
  /** The unread count on the dock, launcher, taskbar and tray tooltip. */
  setBadge(options: { count: number; overlay?: string; tooltip: string }): Promise<void>;
  /** Name the tray menu, which puts the tray up on Windows and Linux. */
  setTray(menu: DesktopTrayMenu): Promise<void>;
  getSettings(): Promise<{ tray: boolean; keepRunning: boolean; openAtLogin: boolean }>;
  setKeepRunning(options: { enabled: boolean }): Promise<void>;
  setOpenAtLogin(options: { enabled: boolean }): Promise<void>;
  /** Colour the window's own buttons at the end of the title bar (Windows, Linux). */
  setTitleBarColors(options: { color: string; symbolColor: string }): Promise<void>;
  addListener(
    eventName: "notificationClicked",
    listener: (event: { tag: string }) => void
  ): Promise<{ remove: () => Promise<void> }>;
}

const Desktop = registerPlugin<DesktopPlugin>("Desktop");

export default Desktop;
