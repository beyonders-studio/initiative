import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, normalize, sep } from "node:path";

import { unzipSync } from "fflate";

import { app, type BrowserWindow, net } from "./app.mjs";
import { mainWindow } from "./desktop.mjs";

type BundleStatus = "success" | "error" | "pending" | "downloading";

interface BundleInfo {
  id: string;
  version: string;
  downloaded: string;
  checksum: string;
  status: BundleStatus;
}

interface State {
  bundles: BundleInfo[];
  /** The bundle last switched to, until it confirms it started. */
  applied: string | null;
  /** The bundle folder running before it, to go back to if it does not; null for the app's own. */
  previous?: string | null;
  /** The app version these bundles were downloaded under. */
  native: string | null;
}

interface BundlesService {
  getActiveBundlePath(): string | null;
  setActiveBundle(directory: string | null, options?: { bootWatchdog?: boolean }): Promise<void>;
}

/**
 * How long a bundle's page has to confirm it started, counted from when its
 * files have loaded: reading a newly unpacked bundle can be slow, and is not
 * the bundle failing.
 */
const READY_AFTER_LOAD_MS = 15_000;

/** A load the page itself superseded, which is not a failure. */
const ERR_ABORTED = -3;

/** The web code the app was installed with. */
const BUILTIN: BundleInfo = {
  id: "builtin",
  version: "builtin",
  downloaded: "",
  checksum: "",
  status: "success",
};

/**
 * What `@capgo/capacitor-updater` does on a phone, for the calls the app makes:
 * a web bundle downloaded from the server, checked against the sha256 its
 * signed statement names, unpacked beside the app's other data and switched
 * to. A bundle that does not confirm it started is rolled back to the one
 * before it: here, rather than by the platform's own watchdog, which gives
 * the page a fixed time from the switch however slowly its files load.
 */
export class CapacitorUpdater {
  static __capacitorElectronPlugin = {
    name: "CapacitorUpdater",
    methods: ["current", "list", "download", "set", "delete", "notifyAppReady"],
  };

  private readonly bundles: BundlesService;
  /** Stops watching the page a switch reloaded. */
  private unwatch = () => {};

  constructor({ services }: { services: { bundles: BundlesService } }) {
    this.bundles = services.bundles;
  }

  /** Before the first window: a newly installed app starts on its own web code. */
  async load() {
    let state = this.read();
    // Switched to, and the app closed before it confirmed it started.
    if (state.applied !== null) {
      state = await this.rollBack(state);
    }
    const native = app.getVersion();
    if (state.native === native) return;
    if (state.native !== null) {
      await this.bundles.setActiveBundle(null);
      rmSync(this.root, { recursive: true, force: true });
    }
    this.write({ bundles: state.native === null ? state.bundles : [], applied: null, native });
  }

  async current() {
    const active = this.bundles.getActiveBundlePath();
    const bundle = this.read().bundles.find((b) => this.dir(b.id) === active) ?? BUILTIN;
    return { bundle, native: app.getVersion() };
  }

  async list() {
    return { bundles: this.read().bundles };
  }

  async download({ url, version, checksum }: { url: string; version: string; checksum: string }) {
    const id = randomUUID();
    const state = this.read();
    state.bundles.push({
      id,
      version,
      downloaded: new Date().toISOString(),
      checksum,
      status: "downloading",
    });
    this.write(state);
    try {
      // Chromium's network stack, not Node's, fetches and decodes the bundle.
      // Every version is served at one URL, cached as immutable, so skip the cache.
      const response = await net.fetch(url, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`The bundle download answered ${response.status}.`);
      }
      const zip = new Uint8Array(await response.arrayBuffer());
      if (createHash("sha256").update(zip).digest("hex") !== checksum) {
        throw new Error("The bundle does not match its checksum.");
      }
      this.unpack(zip, this.dir(id));
      this.dropFailed();
      return this.mark(id, "pending");
    } catch (error) {
      rmSync(this.dir(id), { recursive: true, force: true });
      this.mark(id, "error");
      throw error;
    }
  }

  async set({ id }: { id: string }) {
    const state = this.read();
    const bundle = state.bundles.find((b) => b.id === id);
    if (!bundle || (bundle.status !== "pending" && bundle.status !== "success")) {
      throw new Error(`Bundle ${id} is not ready.`);
    }
    this.write({ ...state, applied: id, previous: this.bundles.getActiveBundlePath() });
    this.watch(mainWindow());
    await this.bundles.setActiveBundle(this.dir(id), { bootWatchdog: false });
  }

  async delete({ id }: { id: string }) {
    const state = this.read();
    if (!state.bundles.some((b) => b.id === id)) {
      throw new Error(`Bundle ${id} is not one this app downloaded.`);
    }
    if (this.bundles.getActiveBundlePath() === this.dir(id)) {
      throw new Error(`Bundle ${id} is the one running.`);
    }
    rmSync(this.dir(id), { recursive: true, force: true });
    this.write({ ...state, bundles: state.bundles.filter((b) => b.id !== id) });
  }

  /** The running bundle started. The ones it replaced are no longer needed. */
  async notifyAppReady() {
    this.unwatch();
    const state = this.read();
    if (state.applied !== null) {
      const applied = state.applied;
      for (const bundle of state.bundles) {
        if (bundle.id !== applied && bundle.status !== "downloading") {
          rmSync(this.dir(bundle.id), { recursive: true, force: true });
        }
      }
      this.write({
        ...state,
        applied: null,
        previous: null,
        bundles: state.bundles
          .filter((b) => b.id === applied || b.status === "downloading")
          .map((b) => (b.id === applied ? { ...b, status: "success" } : b)),
      });
    }
    return { bundle: (await this.current()).bundle };
  }

  /**
   * Roll back when the reloaded page fails to load, its renderer goes, or it
   * loads and does not confirm it started. Without a window, the next launch
   * decides.
   */
  private watch(window: InstanceType<typeof BrowserWindow> | null) {
    this.unwatch();
    if (!window) {
      return;
    }
    const contents = window.webContents;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const failed = () => {
      this.unwatch();
      const state = this.read();
      if (state.applied !== null) {
        void this.rollBack(state);
      }
    };
    const loaded = () => {
      timer = setTimeout(failed, READY_AFTER_LOAD_MS);
    };
    const loadFailed = (
      _event: unknown,
      code: number,
      _text: string,
      _url: string,
      mainFrame: boolean
    ) => {
      if (mainFrame && code !== ERR_ABORTED) {
        failed();
      }
    };
    contents.once("did-finish-load", loaded);
    contents.on("did-fail-load", loadFailed);
    contents.on("render-process-gone", failed);
    this.unwatch = () => {
      clearTimeout(timer);
      contents.off("did-finish-load", loaded);
      contents.off("did-fail-load", loadFailed);
      contents.off("render-process-gone", failed);
      this.unwatch = () => {};
    };
  }

  /** Back to the bundle before the one that did not start, which is not offered again. */
  private async rollBack(state: State): Promise<State> {
    const failed = state.applied;
    const settled: State = {
      ...state,
      applied: null,
      previous: null,
      bundles: state.bundles.map((b) => (b.id === failed ? { ...b, status: "error" } : b)),
    };
    // Recorded first: the page the switch reloads must not take itself for the bundle that failed.
    this.write(settled);
    if (failed !== null && this.bundles.getActiveBundlePath() === this.dir(failed)) {
      const previous = state.previous ?? null;
      const back = previous !== null && existsSync(join(previous, "index.html")) ? previous : null;
      await this.bundles.setActiveBundle(back, { bootWatchdog: false });
    }
    return settled;
  }

  /** A failed bundle is never switched to again, so its replacement takes its place on disk. */
  private dropFailed() {
    const state = this.read();
    for (const bundle of state.bundles) {
      if (bundle.status === "error") {
        rmSync(this.dir(bundle.id), { recursive: true, force: true });
      }
    }
    this.write({ ...state, bundles: state.bundles.filter((b) => b.status !== "error") });
  }

  /** Every entry lands inside the bundle's own folder. */
  private unpack(zip: Uint8Array, target: string) {
    for (const [name, data] of Object.entries(unzipSync(zip))) {
      if (name.endsWith("/")) continue;
      const path = normalize(join(target, name));
      if (!path.startsWith(target + sep)) {
        throw new Error(`The bundle holds ${name}, outside its folder.`);
      }
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, data);
    }
    if (!existsSync(join(target, "index.html"))) {
      throw new Error("The bundle has no index.html.");
    }
  }

  private mark(id: string, status: BundleStatus): BundleInfo {
    const state = this.read();
    const bundles = state.bundles.map((b) => (b.id === id ? { ...b, status } : b));
    this.write({ ...state, bundles });
    return bundles.find((b) => b.id === id) as BundleInfo;
  }

  private get root() {
    return join(app.getPath("userData"), "updates");
  }

  private dir(id: string) {
    return join(this.root, id);
  }

  private get stateFile() {
    return join(this.root, "bundles.json");
  }

  private read(): State {
    try {
      return JSON.parse(readFileSync(this.stateFile, "utf8")) as State;
    } catch {
      return { bundles: [], applied: null, native: null };
    }
  }

  private write(state: State) {
    mkdirSync(this.root, { recursive: true });
    writeFileSync(this.stateFile, JSON.stringify(state, null, 2));
  }
}
