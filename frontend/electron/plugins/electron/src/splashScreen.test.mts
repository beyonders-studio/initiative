/**
 * The splash over the window during an update: in the page's own theme,
 * covering the whole window until the new page hides it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const electron = vi.hoisted(() => {
  const Emitter = process.getBuiltinModule("node:events").EventEmitter;
  class FakeView {
    static made: FakeView[] = [];
    setBackgroundColor = vi.fn();
    setBounds = vi.fn();
    webContents = Object.assign(new Emitter(), {
      setWindowOpenHandler: vi.fn(),
      loadFile: vi.fn(async () => {}),
      close: vi.fn(),
    });
    constructor() {
      FakeView.made.push(this);
    }
  }
  const app = Object.assign(new Emitter(), { getAppPath: () => "/app" });
  return { Emitter, FakeView, app, windows: [] as unknown[], dark: false };
});

vi.mock("./app.mjs", () => ({
  app: electron.app,
  BrowserWindow: { getAllWindows: () => electron.windows },
  nativeTheme: {
    get shouldUseDarkColors() {
      return electron.dark;
    },
  },
  WebContentsView: electron.FakeView,
}));

import { SplashScreen } from "./splashScreen.mjs";

/** The app's window, showing a page in `theme`. */
const window = (theme: "light" | "dark") => {
  const made = Object.assign(new electron.Emitter(), {
    size: [1280, 860],
    getContentSize: () => made.size,
    setBackgroundColor: vi.fn(),
    isDestroyed: () => false,
    getParentWindow: () => null,
    contentView: { addChildView: vi.fn(), removeChildView: vi.fn() },
    webContents: {
      getURL: () => "capacitor://studio.beyonders.initiative/",
      executeJavaScript: async () => theme === "dark",
    },
  });
  electron.windows = [made];
  return made;
};

afterEach(() => {
  electron.app.removeAllListeners();
  electron.FakeView.made = [];
});

describe("the update splash", () => {
  it("covers the window in the page's theme until the new page hides it", async () => {
    // The computer is light; the person chose dark.
    const main = window("dark");
    const splash = new SplashScreen();

    await splash.show();
    const [view] = electron.FakeView.made;
    expect(main.contentView.addChildView).toHaveBeenCalledWith(view);
    expect(main.setBackgroundColor).toHaveBeenCalledWith("#020618");
    expect(view.webContents.loadFile).toHaveBeenCalledWith("/app/assets/splash.html", {
      hash: "dark",
    });
    main.size = [800, 600];
    main.emit("resize");
    expect(view.setBounds).toHaveBeenLastCalledWith({ x: 0, y: 0, width: 800, height: 600 });

    await splash.hide();
    expect(main.contentView.removeChildView).toHaveBeenCalledWith(view);
    expect(view.webContents.close).toHaveBeenCalled();
    await splash.hide();
    expect(view.webContents.close).toHaveBeenCalledTimes(1);
  });

  it("starts every window in the computer's theme", () => {
    electron.dark = true;
    new SplashScreen().load();
    const created = { setBackgroundColor: vi.fn() };

    electron.app.emit("browser-window-created", {}, created);

    expect(created.setBackgroundColor).toHaveBeenCalledWith("#020618");
  });
});
