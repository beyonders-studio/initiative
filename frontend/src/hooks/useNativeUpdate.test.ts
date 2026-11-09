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
  it("joins the manifest path to the origin, ignoring the /api/v1 suffix on serverUrl", () => {
    expect(
      buildBundleDownloadUrl("https://app.example.com/api/v1", "/api/v1/native/bundle/download")
    ).toBe("https://app.example.com/api/v1/native/bundle/download");
  });

  it("preserves a non-standard port and http scheme (LAN self-hosting)", () => {
    expect(
      buildBundleDownloadUrl("http://192.168.1.10:8173/api/v1", "/api/v1/native/bundle/download")
    ).toBe("http://192.168.1.10:8173/api/v1/native/bundle/download");
  });

  it("does not double up the /api/v1 segment", () => {
    const url = buildBundleDownloadUrl("https://host/api/v1", "/api/v1/native/bundle/download");
    expect(url.match(/\/api\/v1/g)).toHaveLength(1);
  });
});

describe("floorFor", () => {
  const statement = {
    v: 1,
    version: "0.75.0",
    sha256: "",
    minNativeVersion: "0.73.0",
    minDesktopVersion: "0.75.0",
  } as const;

  it("holds the phone app to the phone floor", () => {
    expect(floorFor(statement, "android")).toBe("0.73.0");
  });

  it("holds the desktop app to its own floor", () => {
    expect(floorFor(statement, "electron")).toBe("0.75.0");
  });
});

describe("decideNativeUpdate", () => {
  const base = { currentVersion: "0.48.0", nativeVersion: "0.48.0", minNativeVersion: "0.48.0" };

  it("is up-to-date only when the server's version is exactly the running bundle's", () => {
    expect(decideNativeUpdate({ ...base, manifestVersion: "0.48.0" })).toBe("up-to-date");
    // A suffix is part of the version, and the patch number is read past it.
    expect(decideNativeUpdate({ ...base, manifestVersion: "0.48.0-dev-abc" })).toBe("download");
    expect(decideNativeUpdate({ ...base, manifestVersion: "0.48.3-dev-abc" })).toBe("download");
  });

  it("downloads when the server is newer", () => {
    expect(decideNativeUpdate({ ...base, manifestVersion: "0.49.0" })).toBe("download");
  });

  it("goes back to an older bundle that is still no older than the app shipped with", () => {
    expect(
      decideNativeUpdate({ ...base, currentVersion: "0.49.0", manifestVersion: "0.48.1" })
    ).toBe("download");
  });

  it("never installs a bundle older than the one the app shipped with", () => {
    expect(decideNativeUpdate({ ...base, manifestVersion: "0.47.9" })).toBe("older-than-app");
    expect(
      decideNativeUpdate({ ...base, currentVersion: "0.49.0", manifestVersion: "0.47.0" })
    ).toBe("older-than-app");
  });

  it("still installs a suffixed build of the version the app shipped with", () => {
    expect(
      decideNativeUpdate({ ...base, currentVersion: "0.48.1", manifestVersion: "0.48.0-dev-abc" })
    ).toBe("download");
  });

  it("takes only patch releases over the air on iOS", () => {
    const ios = { ...base, platform: "ios" };
    expect(decideNativeUpdate({ ...ios, manifestVersion: "0.48.3" })).toBe("download");
    expect(decideNativeUpdate({ ...ios, manifestVersion: "0.48.3-dev-abc" })).toBe("download");
    expect(decideNativeUpdate({ ...ios, manifestVersion: "0.49.0" })).toBe("native-required");
    expect(decideNativeUpdate({ ...ios, manifestVersion: "1.48.0" })).toBe("native-required");
    // Other platforms keep taking feature releases.
    expect(decideNativeUpdate({ ...base, platform: "android", manifestVersion: "0.49.0" })).toBe(
      "download"
    );
  });

  it("requires a native update when the bundle needs a newer shell than installed", () => {
    expect(
      decideNativeUpdate({
        manifestVersion: "0.50.0",
        currentVersion: "0.48.0",
        nativeVersion: "0.48.0", // installed APK predates the native change
        minNativeVersion: "0.50.0",
      })
    ).toBe("native-required");
  });

  it("downloads when the installed shell is new enough for the bundle", () => {
    expect(
      decideNativeUpdate({
        manifestVersion: "0.50.0",
        currentVersion: "0.48.0",
        nativeVersion: "0.50.0",
        minNativeVersion: "0.49.0",
      })
    ).toBe("download");
  });

  it("prefers up-to-date over native-required when already running the served version", () => {
    expect(
      decideNativeUpdate({
        manifestVersion: "0.48.0",
        currentVersion: "0.48.0",
        nativeVersion: "0.48.0",
        minNativeVersion: "0.99.0",
      })
    ).toBe("up-to-date");
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
  it("returns the downloaded (pending) bundle for the requested version", () => {
    const ready = bundle({ id: "9", version: "0.49.0", status: "pending" });
    expect(findReadyBundle([bundle({ version: "0.48.0" }), ready], "0.49.0")).toBe(ready);
  });

  it("also accepts an already-confirmed (success) bundle for the version (reuse/downgrade)", () => {
    const ready = bundle({ id: "9", version: "0.49.0", status: "success" });
    expect(findReadyBundle([ready], "0.49.0")).toBe(ready);
  });

  it("ignores a bundle that is still downloading (set() would throw)", () => {
    expect(
      findReadyBundle([bundle({ version: "0.49.0", status: "downloading" })], "0.49.0")
    ).toBeNull();
  });

  it("ignores an errored bundle for the version (would roll back and re-prompt)", () => {
    expect(findReadyBundle([bundle({ version: "0.49.0", status: "error" })], "0.49.0")).toBeNull();
  });

  it("ignores a pending bundle for a different version", () => {
    expect(
      findReadyBundle([bundle({ version: "0.48.0", status: "pending" })], "0.49.0")
    ).toBeNull();
  });

  it("returns null when no bundles are present", () => {
    expect(findReadyBundle([], "0.49.0")).toBeNull();
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
