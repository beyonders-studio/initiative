/**
 * The desktop app's bundle updater: a bundle is kept only when it matches its
 * checksum and stays inside its folder, one whose page does not start is
 * rolled back and not offered again, and only bundles it downloaded can be
 * deleted.
 */
import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { strToU8, zipSync } from "fflate";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const paths = vi.hoisted(() => ({
  userData: "",
  windows: [] as unknown[],
  fetch: (async () => new Response()) as (url: string, init?: RequestInit) => Promise<Response>,
}));
vi.mock("./app.mjs", () => ({
  app: { getPath: () => paths.userData, getVersion: () => "1.0.0" },
  BrowserWindow: { getAllWindows: () => paths.windows },
  net: { fetch: (url: string, init?: RequestInit) => paths.fetch(url, init) },
}));

import { CapacitorUpdater } from "./updater.mjs";

const zip = (files: Record<string, string>) =>
  zipSync(Object.fromEntries(Object.entries(files).map(([name, body]) => [name, strToU8(body)])));
const sha = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

/** The platform's bundle service, switching where it is told. */
const platform = () => {
  let active: string | null = null;
  return {
    getActiveBundlePath: () => active,
    setActiveBundle: vi.fn(async (directory: string | null) => {
      active = directory;
    }),
  };
};

/** The app's window, whose page the switch reloads. */
const page = () => {
  const contents = Object.assign(new EventEmitter(), {
    getURL: () => "capacitor://studio.beyonders.initiative/",
  });
  paths.windows = [{ webContents: contents }];
  return contents;
};

/** An updater holding one downloaded bundle, ready to switch to. */
const downloaded = async () => {
  const bundles = platform();
  const updater = new CapacitorUpdater({ services: { bundles } });
  const bytes = zip({ "index.html": "" });
  serve(bytes);
  const bundle = await updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) });
  return { bundles, updater, bundle, bytes };
};

const statuses = async (updater: CapacitorUpdater) =>
  (await updater.list()).bundles.map((b) => b.status);

const serve = (bytes: Uint8Array) => {
  paths.fetch = vi.fn(async () => new Response(bytes));
};

beforeEach(() => {
  paths.userData = mkdtempSync(join(tmpdir(), "initiative-updater-"));
  paths.windows = [];
});

afterEach(() => {
  vi.useRealTimers();
  rmSync(paths.userData, { recursive: true, force: true });
});

describe("the desktop bundle updater", () => {
  it("keeps a bundle that matches its checksum and refuses one that does not", async () => {
    const bundles = platform();
    const updater = new CapacitorUpdater({ services: { bundles } });
    const bytes = zip({ "index.html": "<!doctype html>", "assets/app.js": "" });
    serve(bytes);

    const kept = await updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) });
    await expect(
      updater.download({ url: "u", version: "2.0.1", checksum: "0".repeat(64) })
    ).rejects.toThrow(/checksum/);

    expect(kept.status).toBe("pending");
    expect(existsSync(join(paths.userData, "updates", kept.id, "assets", "app.js"))).toBe(true);
    const { bundles: listed } = await updater.list();
    expect(listed.map((b) => `${b.version}:${b.status}`)).toEqual(["2.0.0:pending", "2.0.1:error"]);
  });

  it("downloads past the cache, since every version is served at one URL", async () => {
    const updater = new CapacitorUpdater({ services: { bundles: platform() } });
    const bytes = zip({ "index.html": "" });
    serve(bytes);

    await updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) });

    expect(paths.fetch).toHaveBeenCalledWith("u", { cache: "no-store" });
  });

  it("refuses a bundle with an entry outside its folder", async () => {
    const updater = new CapacitorUpdater({ services: { bundles: platform() } });
    const bytes = zip({ "index.html": "", "../outside.txt": "" });
    serve(bytes);

    await expect(
      updater.download({ url: "u", version: "2.0.0", checksum: sha(bytes) })
    ).rejects.toThrow(/outside its folder/);
    expect(existsSync(join(paths.userData, "updates", "outside.txt"))).toBe(false);
  });

  it("rolls back a bundle whose page loads and does not confirm it started", async () => {
    const { bundles, updater, bundle } = await downloaded();
    const contents = page();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    await updater.set({ id: bundle.id });
    expect(bundles.setActiveBundle).toHaveBeenLastCalledWith(
      join(paths.userData, "updates", bundle.id),
      { bootWatchdog: false }
    );
    contents.emit("did-finish-load");
    await vi.advanceTimersByTimeAsync(15_000);

    expect(bundles.setActiveBundle).toHaveBeenLastCalledWith(null, { bootWatchdog: false });
    expect(await statuses(updater)).toEqual(["error"]);
  });

  it("keeps a bundle that confirms it started, however long its files take to load", async () => {
    const { bundles, updater, bundle } = await downloaded();
    const contents = page();
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });

    await updater.set({ id: bundle.id });
    await vi.advanceTimersByTimeAsync(60_000);
    contents.emit("did-finish-load");
    await updater.notifyAppReady();
    await vi.advanceTimersByTimeAsync(60_000);

    expect(bundles.setActiveBundle).toHaveBeenCalledTimes(1);
    expect(await statuses(updater)).toEqual(["success"]);
  });

  it("rolls back a bundle whose page fails to load", async () => {
    const { bundles, updater, bundle } = await downloaded();
    const contents = page();

    await updater.set({ id: bundle.id });
    // A load the page itself superseded is not a failure.
    contents.emit("did-fail-load", {}, -3, "", "", true);
    expect(await statuses(updater)).toEqual(["pending"]);
    contents.emit("did-fail-load", {}, -6, "", "", true);
    await vi.waitFor(() => expect(bundles.getActiveBundlePath()).toBeNull());

    expect(await statuses(updater)).toEqual(["error"]);
  });

  it("rolls back at launch a bundle the app closed before it confirmed", async () => {
    const { bundles, updater, bundle } = await downloaded();
    await updater.set({ id: bundle.id });

    await new CapacitorUpdater({ services: { bundles } }).load();

    expect(bundles.getActiveBundlePath()).toBeNull();
    expect(await statuses(updater)).toEqual(["error"]);
  });

  it("drops a failed bundle once its replacement downloads", async () => {
    const { bundles, updater, bundle, bytes } = await downloaded();
    await updater.set({ id: bundle.id });
    await new CapacitorUpdater({ services: { bundles } }).load();

    const replacement = await updater.download({
      url: "u",
      version: "2.0.0",
      checksum: sha(bytes),
    });

    expect((await updater.list()).bundles.map((b) => b.id)).toEqual([replacement.id]);
    expect(existsSync(join(paths.userData, "updates", bundle.id))).toBe(false);
  });

  it("deletes only a bundle it downloaded", async () => {
    const updater = new CapacitorUpdater({ services: { bundles: platform() } });

    await expect(updater.delete({ id: ".." })).rejects.toThrow(/not one this app downloaded/);
    expect(existsSync(paths.userData)).toBe(true);
  });
});
