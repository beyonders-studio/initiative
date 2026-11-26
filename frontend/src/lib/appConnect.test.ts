/**
 * A plug-in connection started in the app: what the connect request carries,
 * which links are a connection handed back, and how one is finished.
 */
import { Capacitor } from "@capacitor/core";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { clearStoredServerUrl, setStoredServerUrl } from "@/lib/serverStorage";
import { CREDENTIAL_KEYS, removeItem } from "@/lib/storage";

import { beginConnect, finishConnect, isConnectHandback } from "./appConnect";

const onPlatform = (platform: string) =>
  vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);

let finished: unknown[] = [];

beforeEach(async () => {
  finished = [];
  await removeItem(CREDENTIAL_KEYS.pendingConnect);
  clearStoredServerUrl();
  server.use(
    http.post("*/plugin-connections/finish", async ({ request }) => {
      finished.push(await request.json());
      return HttpResponse.json({ outcome: "connected" });
    })
  );
});

describe("starting a connection", () => {
  it("sends nothing from a browser, and which app it is and a challenge from an app", async () => {
    onPlatform("web");
    expect(await beginConnect()).toBeUndefined();

    onPlatform("electron");
    expect(await beginConnect()).toEqual({
      app: "desktop",
      code_challenge: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/),
    });
    onPlatform("android");
    expect((await beginConnect())?.app).toBe("phone");
  });
});

describe("a connection handed back", () => {
  it("is the server's handback address, or the app's own link", () => {
    for (const address of [
      "https://initiativetasks.com/api/v1/plugin-connections/handback?code=c",
      "initiative://plugins/connected?outcome=awaiting_approval",
    ]) {
      expect(isConnectHandback(new URL(address))).toBe(true);
    }
    for (const address of [
      "https://initiativetasks.com/plugins/connected?outcome=connected",
      "initiative://oidc/callback?code=c",
    ]) {
      expect(isConnectHandback(new URL(address))).toBe(false);
    }
  });

  /** Start a connection, and answer its handback address with `params`. */
  const started = async (params: string) => {
    const begun = await beginConnect();
    return new URL(
      `https://server.test/api/v1/plugin-connections/handback?${params}&challenge=${begun?.code_challenge}`
    );
  };

  it("is finished once, with the verifier kept when it began", async () => {
    onPlatform("electron");
    const handback = await started("code=h");

    expect(await finishConnect(handback)).toBe("connected");
    expect(finished).toEqual([
      { code: "h", code_verifier: expect.stringMatching(/^[A-Za-z0-9_-]{43}$/) },
    ]);
    // Taken: the same link again finishes nothing.
    expect(await finishConnect(handback)).toBeNull();
    expect(finished).toHaveLength(1);
  });

  it("finds its own verifier while another connection is under way", async () => {
    onPlatform("android");
    const first = await started("code=one");
    const second = await started("code=two");

    await finishConnect(second);
    await finishConnect(first);

    const [two, one] = finished as { code: string; code_verifier: string }[];
    expect([two.code, one.code]).toEqual(["two", "one"]);
    expect(two.code_verifier).not.toBe(one.code_verifier);
  });

  it("is not sent to a server the app moved to after it began", async () => {
    onPlatform("android");
    setStoredServerUrl("https://one.example/api/v1");
    const handback = await started("code=h");

    setStoredServerUrl("https://two.example/api/v1");

    expect(await finishConnect(handback)).toBeNull();
    expect(finished).toEqual([]);
  });

  it("reads an ending that carries no code, and nothing for a connection this app never began", async () => {
    const stranger = new URL(
      "initiative://plugins/connected?outcome=awaiting_approval&challenge=unknown"
    );
    expect(await finishConnect(stranger)).toBeNull();

    onPlatform("android");
    expect(await finishConnect(await started("outcome=awaiting_approval"))).toBe(
      "awaiting_approval"
    );
    expect(await finishConnect(await started("outcome=edited"))).toBe("expired");
    expect(finished).toEqual([]);
  });
});
