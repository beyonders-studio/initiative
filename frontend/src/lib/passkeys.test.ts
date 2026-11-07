/**
 * Where a ceremony runs: the app's own plug-in on Android and the Windows
 * desktop app, the browser everywhere else, and the browser again for a server
 * the app could not act for.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  platform: "android",
  getPasskey: vi.fn(),
  createPasskey: vi.fn(),
  finishPasskeyStepUp: vi.fn(),
  finishPasskeySignUp: vi.fn(),
}));

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => mocks.platform !== "web",
    getPlatform: () => mocks.platform,
    isPluginAvailable: (name: string) => name === "Passkeys",
  },
}));

vi.mock("@capawesome/capacitor-passkeys", () => ({
  Passkeys: {
    getPasskey: (options: unknown) => mocks.getPasskey(options),
    createPasskey: (options: unknown) => mocks.createPasskey(options),
  },
}));

vi.mock("@/api/generated/auth/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/generated/auth/auth")>()),
  beginPasskeyStepUp: () => Promise.resolve({ options: { challenge: "c", rpId: "example.com" } }),
  finishPasskeyStepUp: (body: unknown) => mocks.finishPasskeyStepUp(body),
  beginPasskeySignUp: () =>
    Promise.resolve({ options: { challenge: "s", rp: { id: "example.com" } } }),
  finishPasskeySignUp: (body: unknown) => mocks.finishPasskeySignUp(body),
}));

// A browser that would run a ceremony, so an app is seen refusing one anyway.
vi.mock("@simplewebauthn/browser", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@simplewebauthn/browser")>()),
  browserSupportsWebAuthn: () => true,
}));

vi.mock("@/api/generated/access-grants/access-grants", () => ({
  beginBreakGlassPasskey: () =>
    Promise.resolve({ options: { challenge: "b", rpId: "example.com" } }),
}));

import { setStoredServerUrl } from "@/lib/serverStorage";
import { listKeys, removeItem } from "@/lib/storage";

import {
  appRunsPasskeys,
  assertForBreakGlass,
  describePasskeyPromptError,
  PasskeyNeedsBrowserError,
  passkeysRunHere,
  signUpWithPasskey,
  stepUpWithPasskey,
} from "./passkeys";

beforeEach(() => {
  mocks.platform = "android";
  // An app keeps its storage in memory, which the shared setup leaves alone.
  for (const key of listKeys()) void removeItem(key);
  setStoredServerUrl("https://one.example.com/api/v1");
});

describe("appRunsPasskeys", () => {
  it("is the Android and desktop apps', not a browser's or iOS's", () => {
    expect(appRunsPasskeys()).toBe(true);
    mocks.platform = "electron";
    expect(appRunsPasskeys()).toBe(true);
    mocks.platform = "ios";
    expect(appRunsPasskeys()).toBe(false);
    mocks.platform = "web";
    expect(appRunsPasskeys()).toBe(false);
  });
});

describe("passkeysRunHere", () => {
  it("needs the app's plug-in in an app, whatever the browser says", () => {
    expect(passkeysRunHere()).toBe(true);
    mocks.platform = "ios";
    expect(passkeysRunHere()).toBe(false);
    mocks.platform = "web";
    expect(passkeysRunHere()).toBe(true);
  });
});

describe("a ceremony in the app", () => {
  it("hands the server's options to the plugin and its answer back", async () => {
    mocks.getPasskey.mockResolvedValue({ id: "cred", rawId: "cred", type: "public-key" });
    mocks.finishPasskeyStepUp.mockResolvedValue({ access_token: "t" });

    await stepUpWithPasskey();

    expect(mocks.getPasskey).toHaveBeenCalledWith({ challenge: "c", rpId: "example.com" });
    expect(mocks.finishPasskeyStepUp).toHaveBeenCalledWith({
      credential: { id: "cred", rawId: "cred", type: "public-key" },
    });
  });

  it("tells the desktop plug-in which server to act for", async () => {
    mocks.platform = "electron";
    mocks.getPasskey.mockResolvedValue({ id: "cred" });
    mocks.finishPasskeyStepUp.mockResolvedValue({ access_token: "t" });

    await stepUpWithPasskey();

    expect(mocks.getPasskey).toHaveBeenCalledWith({
      challenge: "c",
      rpId: "example.com",
      origin: "https://one.example.com",
    });
  });

  it("makes an account and answers break-glass through the plug-in too", async () => {
    mocks.createPasskey.mockResolvedValue({ id: "new" });
    mocks.finishPasskeySignUp.mockResolvedValue({ access_token: "t" });
    mocks.getPasskey.mockResolvedValue({ id: "cred" });

    await signUpWithPasskey({ email: "a@example.com" } as never);
    expect(mocks.createPasskey).toHaveBeenCalledWith({ challenge: "s", rp: { id: "example.com" } });
    expect(mocks.finishPasskeySignUp).toHaveBeenCalledWith(
      expect.objectContaining({ credential: { id: "new" } })
    );

    await expect(assertForBreakGlass()).resolves.toEqual({ id: "cred" });
    expect(mocks.getPasskey).toHaveBeenCalledWith({ challenge: "b", rpId: "example.com" });
  });

  it("sends a server the phone refused to the browser, and only that server", async () => {
    mocks.getPasskey.mockRejectedValue({ code: "DOMAIN_NOT_ASSOCIATED" });

    const refused = await stepUpWithPasskey().catch((err: unknown) => err);
    expect(refused).toBeInstanceOf(PasskeyNeedsBrowserError);
    expect(describePasskeyPromptError(refused)).toBe("auth:login.passkeyNotInApp");
    expect(appRunsPasskeys()).toBe(false);

    setStoredServerUrl("https://two.example.com/api/v1");
    expect(appRunsPasskeys()).toBe(true);

    // A second refusal keeps the first.
    await expect(stepUpWithPasskey()).rejects.toBeInstanceOf(PasskeyNeedsBrowserError);
    setStoredServerUrl("https://one.example.com/api/v1");
    expect(appRunsPasskeys()).toBe(false);
  });

  it("gives a put-down prompt the browser's name for it", async () => {
    mocks.getPasskey.mockRejectedValue({ code: "CANCELED" });

    await expect(stepUpWithPasskey()).rejects.toMatchObject({ name: "NotAllowedError" });
    expect(appRunsPasskeys()).toBe(true);
  });

  it("reads the browser's own names, which the desktop plug-in passes on", async () => {
    mocks.platform = "electron";
    mocks.getPasskey.mockRejectedValue({ code: "InvalidStateError" });
    await expect(stepUpWithPasskey()).rejects.toMatchObject({ name: "InvalidStateError" });

    mocks.getPasskey.mockRejectedValue({ code: "SecurityError" });
    await expect(stepUpWithPasskey()).rejects.toBeInstanceOf(PasskeyNeedsBrowserError);
  });
});
