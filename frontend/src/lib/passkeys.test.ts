/**
 * Where a prompt runs: the app's own plug-in on Android and the Windows
 * desktop app, the system browser in every other app and for a server the
 * plug-in could not act for, and the page in a browser. The ceremony around it
 * is the page's either way.
 */
import { Browser } from "@capacitor/browser";
import { waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  platform: "android",
  getPasskey: vi.fn(),
  createPasskey: vi.fn(),
  finishPasskeyStepUp: vi.fn(),
  beginPasskeySignUp: vi.fn(),
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
  beginPasskeySignUp: (body: unknown) => mocks.beginPasskeySignUp(body),
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
  answerBrowserPrompt,
  appRunsPasskeys,
  assertForBreakGlass,
  describePasskeyPromptError,
  passkeysRunHere,
  signUpWithPasskey,
  stepUpWithPasskey,
} from "./passkeys";

const STEP_UP_OPTIONS = { challenge: "c", rpId: "example.com" };

/** What the system browser hands back, as the app is opened with it. */
const answer = (params: Record<string, string>) =>
  answerBrowserPrompt(new URL(`initiative://passkey/callback?${new URLSearchParams(params)}`));

/** The address the app last opened the system browser at. */
const opened = () => new URL(vi.mocked(Browser.open).mock.calls.at(-1)?.[0].url ?? "");

beforeEach(() => {
  mocks.platform = "android";
  vi.mocked(Browser.open).mockClear();
  vi.mocked(Browser.addListener).mockClear();
  mocks.beginPasskeySignUp.mockResolvedValue({
    options: { challenge: "s", rp: { id: "example.com" } },
  });
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
  it("holds in every app, which has the browser where it has no plug-in", () => {
    expect(passkeysRunHere()).toBe(true);
    mocks.platform = "ios";
    expect(passkeysRunHere()).toBe(true);
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
    // The begin carries the S256 of the verifier the finish carries.
    const { code_challenge } = mocks.beginPasskeySignUp.mock.calls[0][0];
    const { code_verifier, credential } = mocks.finishPasskeySignUp.mock.calls[0][0];
    expect(credential).toEqual({ id: "new" });
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(code_verifier));
    expect(code_challenge).toBe(
      btoa(String.fromCharCode(...new Uint8Array(digest)))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "")
    );

    await expect(assertForBreakGlass()).resolves.toEqual({ id: "cred" });
    expect(mocks.getPasskey).toHaveBeenCalledWith({ challenge: "b", rpId: "example.com" });
  });

  it("sends a server the phone refused to the browser, and only that server", async () => {
    mocks.getPasskey.mockRejectedValue({ code: "DOMAIN_NOT_ASSOCIATED" });
    mocks.finishPasskeyStepUp.mockResolvedValue({ access_token: "t" });

    // The same press goes on in the browser.
    const done = stepUpWithPasskey();
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));
    answer({ credential: JSON.stringify({ id: "cred" }) });
    await done;
    expect(appRunsPasskeys()).toBe(false);

    setStoredServerUrl("https://two.example.com/api/v1");
    expect(appRunsPasskeys()).toBe(true);

    // A second refusal keeps the first.
    const again = stepUpWithPasskey();
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(2));
    answer({ credential: JSON.stringify({ id: "cred" }) });
    await again;
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
    const refused = stepUpWithPasskey();
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));
    answer({ error: "NotAllowedError" });
    await expect(refused).rejects.toMatchObject({ name: "NotAllowedError" });
  });
});

describe("a prompt in the system browser", () => {
  beforeEach(() => {
    mocks.platform = "ios";
    mocks.finishPasskeyStepUp.mockReset().mockResolvedValue({ access_token: "t" });
  });

  it("runs on the server's page and finishes with the answer it hands back", async () => {
    const done = stepUpWithPasskey();
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));

    expect(`${opened().origin}${opened().pathname}${opened().search}`).toBe(
      "https://one.example.com/login?passkey=1"
    );
    expect(JSON.parse(new URLSearchParams(opened().hash.slice(1)).get("get") ?? "")).toEqual(
      STEP_UP_OPTIONS
    );

    expect(answer({ credential: JSON.stringify({ id: "cred" }) })).toBe(true);
    await done;
    expect(mocks.finishPasskeyStepUp).toHaveBeenCalledWith({ credential: { id: "cred" } });
    expect(Browser.close).toHaveBeenCalled();
  });

  it("ends the way the browser's prompt ended", async () => {
    const done = stepUpWithPasskey();
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));
    answer({ error: "NotAllowedError" });

    const ended = await done.catch((err: unknown) => err);
    expect(describePasskeyPromptError(ended)).toBe("auth:login.passkeyCancelled");
    expect(mocks.finishPasskeyStepUp).not.toHaveBeenCalled();
  });

  it("ends when the browser is closed without an answer", async () => {
    const done = stepUpWithPasskey();
    await waitFor(() => expect(Browser.addListener).toHaveBeenCalledTimes(1));
    const [event, closed] = vi.mocked(Browser.addListener).mock.calls[0] as unknown as [
      string,
      () => void,
    ];
    expect(event).toBe("browserFinished");
    closed();

    await expect(done).rejects.toMatchObject({ name: "NotAllowedError" });
  });

  it("puts an older prompt down for a newer one", async () => {
    const first = stepUpWithPasskey();
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(1));
    const second = stepUpWithPasskey();

    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    await waitFor(() => expect(Browser.open).toHaveBeenCalledTimes(2));
    answer({ credential: JSON.stringify({ id: "cred" }) });
    await second;
  });

  it("leaves other links to whoever takes them", () => {
    expect(answerBrowserPrompt(new URL("initiative://oidc/callback?code=x"))).toBe(false);
  });
});
