/**
 * Passkeys in the desktop app: registered on Windows alone, each ceremony run
 * at the server's address over the app window, and its answer handed back.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => {
  // Hoisted above the imports, so Node's own module is fetched directly.
  const Emitter = process.getBuiltinModule("node:events").EventEmitter;
  const handlers = new Map<string, () => Response>();
  const passkeys = Object.assign(new Emitter(), {
    partition: "",
    protocol: {
      handle: (scheme: string, handler: () => Response) => handlers.set(scheme, handler),
    },
  });
  const shown = new Set<unknown>();
  const window = Object.assign(new Emitter(), {
    getContentSize: () => [1280, 860],
    contentView: {
      addChildView: (view: unknown) => shown.add(view),
      removeChildView: (view: unknown) => shown.delete(view),
    },
  });
  const state = { answer: {} as unknown, hasWindow: true };
  class FakeView {
    static made: FakeView[] = [];
    bounds: unknown = null;
    webContents = {
      loadURL: vi.fn(async (_url: string) => undefined),
      focus: vi.fn(),
      executeJavaScript: vi.fn(async (_code: string, _gesture: boolean) => state.answer),
      close: vi.fn(),
    };
    constructor(readonly options: unknown) {
      FakeView.made.push(this);
    }
    setBackgroundColor = vi.fn();
    setBounds = (bounds: unknown) => {
      this.bounds = bounds;
    };
  }
  return { Emitter, handlers, passkeys, shown, window, state, FakeView };
});

vi.mock("./app.mjs", () => ({
  session: {
    fromPartition: (name: string) => {
      fake.passkeys.partition = name;
      return fake.passkeys;
    },
  },
  WebContentsView: fake.FakeView,
}));

vi.mock("./desktop.mjs", () => ({
  mainWindow: () => (fake.state.hasWindow ? fake.window : null),
}));

import { addressFor, Passkeys } from "./passkeys.mjs";

const loaded = () => {
  const plugin = new Passkeys();
  plugin.load();
  return plugin;
};

afterEach(() => {
  fake.passkeys.removeAllListeners();
  fake.FakeView.made = [];
  fake.state.hasWindow = true;
  vi.restoreAllMocks();
});

describe("Passkeys", () => {
  it("registers on Windows alone", () => {
    const platform = vi.spyOn(process, "platform", "get");
    platform.mockReturnValue("win32");
    expect(Passkeys.__capacitorElectronPlugin?.name).toBe("Passkeys");
    for (const other of ["darwin", "linux"] as const) {
      platform.mockReturnValue(other);
      expect(Passkeys.__capacitorElectronPlugin).toBeUndefined();
    }
  });

  it("answers every request in its own session with a local page", async () => {
    loaded();

    expect(fake.passkeys.partition).toBe("passkeys");
    const page = fake.handlers.get("https")?.();
    expect(page?.headers.get("content-security-policy")).toContain("default-src 'none'");
    expect(await page?.text()).toContain("<!doctype html>");
    expect(fake.handlers.has("http")).toBe(true);
  });

  it("runs the ceremony at the server's address over the app window", async () => {
    const plugin = loaded();
    fake.state.answer = { credential: { id: "cred" } };

    const answer = await plugin.getPasskey({
      challenge: "c",
      rpId: "example.com",
      origin: "https://example.com",
    });

    expect(answer).toEqual({ id: "cred" });
    const [view] = fake.FakeView.made;
    expect(view.webContents.loadURL).toHaveBeenCalledWith("https://example.com/");
    expect(view.bounds).toEqual({ x: 0, y: 0, width: 1280, height: 860 });
    const [script, gesture] = view.webContents.executeJavaScript.mock.calls[0];
    expect(script).toContain('{"challenge":"c","rpId":"example.com"}');
    expect(gesture).toBe(true);
    // Gone from the window once the ceremony is over.
    expect(fake.shown.size).toBe(0);
    expect(view.webContents.close).toHaveBeenCalled();
  });

  it("passes on the browser's name for a prompt that ended without a credential", async () => {
    const plugin = loaded();
    fake.state.answer = { error: "NotAllowedError" };

    await expect(
      plugin.createPasskey({
        challenge: "c",
        rp: { id: "example.com" },
        origin: "https://example.com",
      })
    ).rejects.toMatchObject({ code: "NotAllowedError" });
    expect(fake.shown.size).toBe(0);
  });

  it("opens nothing for an address the relying party does not cover", async () => {
    const plugin = loaded();

    await expect(
      plugin.getPasskey({ challenge: "c", rpId: "example.com", origin: "https://example.org" })
    ).rejects.toMatchObject({ code: "NotSupportedError" });
    expect(fake.FakeView.made).toHaveLength(0);

    expect(addressFor("https://app.example.com/api/v1", "example.com")).toBe(
      "https://app.example.com"
    );
    expect(addressFor("http://localhost:5173", "localhost")).toBe("http://localhost:5173");
    expect(addressFor("https://example.com.example.org", "example.com")).toBeNull();
    expect(addressFor("https://notexample.com", "example.com")).toBeNull();
    expect(addressFor("ftp://example.com", "example.com")).toBeNull();
  });

  it("answers Chromium's account question only when there is one account", () => {
    loaded();
    const answer = (accounts: { credentialId: string }[]) => {
      const callback = vi.fn();
      fake.passkeys.emit("select-webauthn-account", {}, { accounts }, callback);
      return callback.mock.calls[0][0];
    };

    expect(answer([{ credentialId: "one" }])).toBe("one");
    expect(answer([{ credentialId: "one" }, { credentialId: "two" }])).toBeUndefined();
  });
});
