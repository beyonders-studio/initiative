import { Capacitor } from "@capacitor/core";
import type { BundleInfo } from "@capgo/capacitor-updater";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePendingUpdate } from "@/lib/pendingUpdate";

import {
  buildBundleDownloadUrl,
  decideNativeUpdate,
  findReadyBundle,
  floorFor,
  useNativeUpdate,
} from "./useNativeUpdate";

// A desktop app on 0.74.0 whose server's update needs the 0.80.0 app.
const native = vi.hoisted(() => ({
  consent: true,
  download: vi.fn(),
  install: vi.fn(),
  toast: vi.fn(),
}));
vi.mock("@/hooks/useServer", () => ({
  useServer: () => ({ serverUrl: "https://s.example/api/v1", isNativePlatform: true }),
}));
vi.mock("@/lib/otaTrust", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/otaTrust")>()),
  verifiedStatement: async (statement: string) => JSON.parse(statement),
}));
vi.mock("@capgo/capacitor-updater", () => ({
  CapacitorUpdater: { current: async () => ({ native: "0.74.0" }) },
}));
vi.mock("@capacitor/app", () => ({
  App: { addListener: async () => ({ remove: () => undefined }) },
}));
vi.mock("@/lib/desktopUpdates", () => ({
  autoUpdateConsented: () => native.consent,
  desktopCanUpdate: async () => true,
}));
vi.mock("@/plugins/desktopUpdater", () => ({
  default: { download: native.download, install: native.install },
}));
vi.mock("@/lib/mascotToast", () => ({ toast: { info: native.toast } }));

const bundle = (over: Partial<BundleInfo>): BundleInfo => ({
  id: "1",
  version: "0.0.0",
  status: "pending",
  downloaded: "",
  checksum: "",
  ...over,
});

/**
 * These pure helpers back the OTA flow in {@link useNativeUpdate}. The load-bearing details:
 * the download URL must join to the server *origin* (not `serverUrl`, which already carries
 * `/api/v1`), and the decision must treat any version difference — including a downgrade — as
 * "not up to date", while refusing bundles that need a newer native shell.
 */
describe("buildBundleDownloadUrl", () => {
  it.each([
    ["https://app.example.com/api/v1", "https://app.example.com/api/v1/native/bundle/download"],
    // A non-standard port and http scheme (LAN self-hosting).
    ["http://192.168.1.10:8173/api/v1", "http://192.168.1.10:8173/api/v1/native/bundle/download"],
  ])("joins the manifest path to the origin of %s, not doubling /api/v1", (serverUrl, url) => {
    expect(buildBundleDownloadUrl(serverUrl, "/api/v1/native/bundle/download")).toBe(url);
  });
});

describe("floorFor", () => {
  it("holds the phone app to the phone floor, and the desktop app to its own", () => {
    const statement = {
      v: 1,
      version: "0.75.0",
      sha256: "",
      minNativeVersion: "0.73.0",
      minDesktopVersion: "0.75.0",
    } as const;
    expect(floorFor(statement, "android")).toBe("0.73.0");
    expect(floorFor(statement, "electron")).toBe("0.75.0");
  });
});

describe("decideNativeUpdate", () => {
  const base = { currentVersion: "0.48.0", nativeVersion: "0.48.0", minNativeVersion: "0.48.0" };
  const ios = { ...base, platform: "ios" };

  it.each([
    // Up to date only when the server's version is exactly the running bundle's.
    ["the same version", { ...base, manifestVersion: "0.48.0" }, "up-to-date"],
    // A suffix is part of the version, and the patch number is read past it.
    ["a suffixed build", { ...base, manifestVersion: "0.48.0-dev-abc" }, "download"],
    ["a suffixed patch", { ...base, manifestVersion: "0.48.3-dev-abc" }, "download"],
    ["a newer server", { ...base, manifestVersion: "0.49.0" }, "download"],
    [
      "an older bundle no older than the app shipped with",
      { ...base, currentVersion: "0.49.0", manifestVersion: "0.48.1" },
      "download",
    ],
    ["a bundle older than the app", { ...base, manifestVersion: "0.47.9" }, "older-than-app"],
    [
      "a downgrade below the app",
      { ...base, currentVersion: "0.49.0", manifestVersion: "0.47.0" },
      "older-than-app",
    ],
    [
      "a suffixed build of the version the app shipped with",
      { ...base, currentVersion: "0.48.1", manifestVersion: "0.48.0-dev-abc" },
      "download",
    ],
    // Only patch releases go over the air on iOS; other platforms take features.
    ["an iOS patch", { ...ios, manifestVersion: "0.48.3" }, "download"],
    ["a suffixed iOS patch", { ...ios, manifestVersion: "0.48.3-dev-abc" }, "download"],
    ["an iOS feature release", { ...ios, manifestVersion: "0.49.0" }, "native-required"],
    ["an iOS major release", { ...ios, manifestVersion: "1.48.0" }, "native-required"],
    [
      "an Android feature release",
      { ...base, platform: "android", manifestVersion: "0.49.0" },
      "download",
    ],
    [
      "a bundle needing a newer shell than installed",
      {
        manifestVersion: "0.50.0",
        currentVersion: "0.48.0",
        nativeVersion: "0.48.0",
        minNativeVersion: "0.50.0",
      },
      "native-required",
    ],
    [
      "a bundle the installed shell is new enough for",
      {
        manifestVersion: "0.50.0",
        currentVersion: "0.48.0",
        nativeVersion: "0.50.0",
        minNativeVersion: "0.49.0",
      },
      "download",
    ],
    [
      "the served version, already running, whatever shell it asks for",
      { ...base, manifestVersion: "0.48.0", minNativeVersion: "0.99.0" },
      "up-to-date",
    ],
  ])("for %s, decides %s", (_case, input, decision) => {
    expect(decideNativeUpdate(input)).toBe(decision);
  });
});

/**
 * `applyUpdate` only swaps to a bundle this gate approves. The load-bearing rule: a freshly
 * downloaded bundle is `"pending"` (Capgo only marks it `"success"` after set() + the booted
 * bundle calls notifyAppReady), so the gate must accept `"pending"` — gating on `"success"`
 * would wait forever and re-show the prompt. It must still reject a still-downloading or errored
 * bundle — handing either to `set()` throws or boots a bundle that rolls back and re-prompts.
 */
describe("findReadyBundle", () => {
  it.each(["pending", "success"] as const)(
    "returns a %s bundle for the requested version",
    (status) => {
      const ready = bundle({ id: "9", version: "0.49.0", status });
      expect(findReadyBundle([bundle({ version: "0.48.0" }), ready], "0.49.0")).toBe(ready);
    }
  );

  it.each([
    ["one still downloading", [bundle({ version: "0.49.0", status: "downloading" })]],
    ["an errored one", [bundle({ version: "0.49.0", status: "error" })]],
    ["a pending one for another version", [bundle({ version: "0.48.0", status: "pending" })]],
    ["none at all", []],
  ])("finds nothing ready among %s", (_case, bundles) => {
    expect(findReadyBundle(bundles, "0.49.0")).toBeNull();
  });
});

describe("useNativeUpdate on a desktop app that may update itself", () => {
  beforeEach(() => {
    native.consent = true;
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("electron");
    const statement = JSON.stringify({
      v: 1,
      version: "0.81.0",
      sha256: "",
      minNativeVersion: "0.73.0",
      minDesktopVersion: "0.80.0",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ version: "0.81.0", url: "/api/v1/x", statement, signature: "s" })
          )
      )
    );
  });

  it("fetches the new app in the background and offers a restart that stays", async () => {
    native.download.mockResolvedValue({ version: "0.80.0" });
    const { result } = renderHook(() => useNativeUpdate());
    const pending = renderHook(() => usePendingUpdate());

    await waitFor(() => expect(native.toast).toHaveBeenCalled());
    expect(native.download).toHaveBeenCalledWith({ version: "0.80.0" });
    const [, options] = native.toast.mock.calls[0];
    options.action.onClick();
    expect(native.install).toHaveBeenCalledTimes(1);
    // The Update button outlasts the toast, and restarts the same way.
    expect(pending.result.current?.action).toBe("restart");
    pending.result.current?.run();
    expect(native.install).toHaveBeenCalledTimes(2);
    expect(result.current.nativeUpdateRequired.show).toBe(false);
  });

  it("asks instead when the background download fails", async () => {
    native.download.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useNativeUpdate());

    await waitFor(() => expect(result.current.nativeUpdateRequired.show).toBe(true));
    expect(result.current.nativeUpdateRequired.minNativeVersion).toBe("0.80.0");
    expect(native.toast).not.toHaveBeenCalled();
  });

  it("asks without consent, downloading nothing", async () => {
    native.consent = false;
    const { result } = renderHook(() => useNativeUpdate());

    await waitFor(() => expect(result.current.nativeUpdateRequired.show).toBe(true));
    expect(native.download).not.toHaveBeenCalled();
  });
});
