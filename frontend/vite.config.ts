import path from "path";
import fs from "fs";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import { defineConfig, loadEnv } from "vite";

import { contentPolicy } from "./electron/content-policy";
import { buildNotices } from "./scripts/third-party-notices.mjs";

// Load VITE_* vars from .env files (checks backend/.env and frontend/)
const env = {
  ...loadEnv("production", path.resolve(import.meta.dirname, "../backend"), "VITE_"),
  ...loadEnv("production", process.cwd(), "VITE_"),
};

const devProxyTarget = process.env.VITE_DEV_PROXY_TARGET ?? "http://localhost:8000";

// Read version from VERSION file at project root
const getVersion = () => {
  try {
    const versionPath = path.resolve(import.meta.dirname, "../VERSION");
    const version = fs.readFileSync(versionPath, "utf-8").trim();
    // Append suffix for dev builds (e.g., "-dev-abc1234")
    const suffix = process.env.VITE_VERSION_SUFFIX || "";
    return version + suffix;
  } catch {
    return "0.0.0";
  }
};

const createProxyConfig = (supportsWebSocket = false) => ({
  target: devProxyTarget,
  changeOrigin: true,
  ws: supportsWebSocket,
});

// The emoji picker (frimousse) fetches its dataset at runtime from
// `${emojibaseUrl}/${locale}/{data,messages}.json`, defaulting to a public CDN.
// A self-hosted install may have no internet at all, so the files are served
// from the app itself: copied out of the `emojibase-data` package into
// `/emojibase/...` at build time, and served straight from node_modules in dev.
// Only the locales the app actually ships translations for are copied.
const EMOJI_LOCALES = ["en", "de", "es", "fr"];
const EMOJI_FILES = ["data.json", "messages.json"];
const EMOJI_BASE_PATH = "/emojibase";

const emojibaseSource = (locale: string, file: string) =>
  path.resolve(import.meta.dirname, "node_modules/emojibase-data", locale, file);

const emojibasePlugin = () => ({
  name: "initiative-emojibase",
  // Dev: answer the same URLs the build will, without a copy step.
  configureServer(server: { middlewares: { use: (fn: unknown) => void } }) {
    server.middlewares.use(
      (
        req: { url?: string },
        res: { setHeader: (k: string, v: string) => void; end: (body?: unknown) => void },
        next: () => void
      ) => {
        // Two gates on the only path here that reads a URL: the pattern
        // admits no dots or slashes in the locale, and the locale must then be
        // one this app ships. Anything else falls through to the SPA.
        const match = req.url?.match(
          /^\/emojibase\/([a-z-]+)\/(data|messages)\.json$/
        );
        if (!match) return next();
        const [, locale, name] = match;
        if (!EMOJI_LOCALES.includes(locale)) return next();
        res.setHeader("Content-Type", "application/json");
        res.end(fs.readFileSync(emojibaseSource(locale, `${name}.json`)));
      }
    );
  },
  // Build: emit the files as static assets at their expected paths.
  generateBundle(this: { emitFile: (f: unknown) => void }) {
    for (const locale of EMOJI_LOCALES) {
      for (const file of EMOJI_FILES) {
        this.emitFile({
          type: "asset",
          fileName: `emojibase/${locale}/${file}`,
          source: fs.readFileSync(emojibaseSource(locale, file), "utf-8"),
        });
      }
    }
  },
});

// The PDF viewer runs pdf.js out of the app itself rather than a CDN: a
// cross-origin worker URL forces pdf.js to import() it from inside a blob
// worker, which `script-src 'self'` blocks, and a self-hosted install may have
// no internet at all. Two sets of files have to travel with it.
//
// The worker lands beside the other WebAssembly workers, because pdf.js 6
// decodes JBIG2, CCITT fax and JPEG 2000 images in WebAssembly (all three were
// plain JavaScript in 5.x) and so needs the policy the backend applies to
// `assets/workers/` — see `_WASM_WORKER_ASSET_PREFIXES` in backend/app/main.py.
//
// The WebAssembly modules themselves are fetched by the worker at runtime from
// the `wasmUrl` API option. Without them a scanned or faxed PDF — the common
// source of JBIG2 and CCITT images — renders blank.
//
// Both paths carry the pdf.js version, so upgrading can't leave a browser
// holding a cached worker from one release and modules from another.
const PDFJS_DIR = path.resolve(import.meta.dirname, "node_modules/pdfjs-dist");
const PDFJS_VERSION: string = JSON.parse(
  fs.readFileSync(path.join(PDFJS_DIR, "package.json"), "utf-8")
).version;
const PDFJS_WORKER_FILE = `assets/workers/pdf.worker-${PDFJS_VERSION}.mjs`;
const PDFJS_WASM_DIR = `assets/pdfjs-wasm/${PDFJS_VERSION}`;
const PDFJS_WORKER_URL = `/${PDFJS_WORKER_FILE}`;
// pdf.js appends the bare filename, so the trailing slash is part of the option.
const PDFJS_WASM_URL = `/${PDFJS_WASM_DIR}/`;

// pdf.js 6's default build calls `Map.prototype.getOrInsertComputed`, which only
// the very newest browsers have — a PDF fails to render outright on anything
// older, which is most of them. The `legacy` build is the same release with the
// polyfills folded back in, so that is what the app ships: this worker, and the
// two aliases under `resolve` that point react-pdf's copy of the API and the
// annotation/text layer at their legacy twins. All three must move together —
// pdf.js refuses a worker that isn't its own version, and mixing a legacy API
// with a default worker would put the untranslated calls back in the page.
const pdfjsWorkerSource = path.join(PDFJS_DIR, "legacy/build/pdf.worker.min.mjs");
const pdfjsWasmFiles = () => fs.readdirSync(path.join(PDFJS_DIR, "wasm"));

const pdfjsPlugin = () => ({
  name: "initiative-pdfjs",
  // Dev: answer the same URLs the build will, without a copy step.
  configureServer(server: { middlewares: { use: (fn: unknown) => void } }) {
    server.middlewares.use(
      (
        req: { url?: string },
        res: { setHeader: (k: string, v: string) => void; end: (body?: unknown) => void },
        next: () => void
      ) => {
        if (req.url === PDFJS_WORKER_URL) {
          res.setHeader("Content-Type", "text/javascript");
          res.end(fs.readFileSync(pdfjsWorkerSource));
          return;
        }
        // Two gates, as above: the pattern admits no dots or slashes in the
        // filename, and the name must then be one the installed pdf.js ships.
        // The directory is escaped because the version in it carries dots.
        const match = req.url?.match(
          new RegExp(
            `^${PDFJS_WASM_URL.replace(/[.]/g, "\\.")}([A-Za-z0-9_]+\\.(?:wasm|js))$`
          )
        );
        if (!match) return next();
        const [, name] = match;
        if (!pdfjsWasmFiles().includes(name)) return next();
        res.setHeader("Content-Type", name.endsWith(".wasm") ? "application/wasm" : "text/javascript");
        res.end(fs.readFileSync(path.join(PDFJS_DIR, "wasm", name)));
      }
    );
  },
  // Build: emit the files as static assets at their expected paths.
  generateBundle(this: { emitFile: (f: unknown) => void }) {
    this.emitFile({
      type: "asset",
      fileName: PDFJS_WORKER_FILE,
      source: fs.readFileSync(pdfjsWorkerSource),
    });
    // Everything pdf.js ships, including the licenses for the binaries and the
    // no-WebAssembly JavaScript fallbacks it reaches for when a browser has
    // WebAssembly disabled.
    for (const name of pdfjsWasmFiles()) {
      this.emitFile({
        type: "asset",
        fileName: `${PDFJS_WASM_DIR}/${name}`,
        source: fs.readFileSync(path.join(PDFJS_DIR, "wasm", name)),
      });
    }
  },
});

// The licence notices of everything third-party the app ships — every
// production package, the native libraries in the phone apps, fonts and
// artwork — written into each build as THIRD_PARTY_NOTICES.txt, because a
// minified bundle strips the notices those licences ask to travel with it.
// The /licences page reads it, from the version dialog. How it is put together
// is in scripts/third-party-notices.mjs; a build fails when a Capacitor plug-in
// or an emitted font has no entry in frontend/licences/.
const THIRD_PARTY_NOTICES_FILE = "THIRD_PARTY_NOTICES.txt";

const thirdPartyNoticesPlugin = () => ({
  name: "initiative-third-party-notices",
  // Dev: generated on request, so the page works under `pnpm dev` too.
  configureServer(server: { middlewares: { use: (fn: unknown) => void } }) {
    server.middlewares.use(
      (
        req: { url?: string },
        res: { setHeader: (k: string, v: string) => void; end: (body?: unknown) => void },
        next: () => void
      ) => {
        if (req.url !== `/${THIRD_PARTY_NOTICES_FILE}`) return next();
        res.setHeader("Content-Type", "text/plain; charset=utf-8");
        res.end(buildNotices().text);
      }
    );
  },
  // Build: after everything else is in the bundle, so the fonts can be checked.
  generateBundle(
    this: { emitFile: (f: unknown) => void },
    _options: unknown,
    bundle: Record<string, unknown>
  ) {
    const { text } = buildNotices({ bundleFiles: Object.keys(bundle) });
    this.emitFile({ type: "asset", fileName: THIRD_PARTY_NOTICES_FILE, source: text });
  },
});

// Use relative paths for Capacitor builds (mobile apps load from file:// or local server)
const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

export default defineConfig({
  base: isCapacitorBuild ? "" : "/",
  define: {
    __APP_VERSION__: JSON.stringify(getVersion()),
    __IS_CAPACITOR__: JSON.stringify(isCapacitorBuild),
    // Absolute, on native too: the Capacitor WebView serves index.html from
    // its origin root, so a relative URL would resolve against whatever route
    // the app happens to be on when the picker first opens.
    __EMOJIBASE_URL__: JSON.stringify(EMOJI_BASE_PATH),
    // Absolute for the same reason as the emoji dataset above.
    __PDFJS_WORKER_URL__: JSON.stringify(PDFJS_WORKER_URL),
    __PDFJS_WASM_URL__: JSON.stringify(PDFJS_WASM_URL),
  },
  plugins: [
    // A route's tests sit beside it and export no Route of their own, so the
    // generator skips them rather than treating each as a missing route.
    // Each route's component loads with the route, so the entry carries only
    // the route tree and what every page needs.
    tanstackRouter({ autoCodeSplitting: true, routeFileIgnorePattern: "\\.test\\.[jt]sx?$" }),
    react(),
    tailwindcss(),
    emojibasePlugin(),
    pdfjsPlugin(),
    thirdPartyNoticesPlugin(),
    // The device apps load index.html from the bundle, so it carries their
    // content policy, ahead of everything the page loads.
    isCapacitorBuild && {
      name: "device-content-policy",
      transformIndexHtml: () => [
        {
          tag: "meta",
          attrs: { "http-equiv": "Content-Security-Policy", content: contentPolicy },
          injectTo: "head-prepend" as const,
        },
      ],
    },
  ],
  resolve: {
    alias: [
      { find: "@", replacement: path.resolve(import.meta.dirname, "./src") },
      // The legacy pdf.js build — see the worker above. Anchored so the other
      // `pdfjs-dist/...` subpaths resolve normally.
      { find: /^pdfjs-dist$/, replacement: path.join(PDFJS_DIR, "legacy/build/pdf.mjs") },
      {
        find: "pdfjs-dist/web/pdf_viewer.mjs",
        replacement: path.join(PDFJS_DIR, "legacy/web/pdf_viewer.mjs"),
      },
    ],
  },
  worker: {
    // Worker bundles land in their own directory so a served response can be
    // matched by path. The backend keys the WebAssembly workers' policy off
    // `assets/workers/sandbox.worker-` and `assets/workers/ratchet.worker-` —
    // see `_WASM_WORKER_ASSET_PREFIXES` in backend/app/main.py, which is pinned
    // by tests on both sides.
    rolldownOptions: {
      output: {
        entryFileNames: "assets/workers/[name]-[hash].js",
        chunkFileNames: "assets/workers/[name]-[hash].js",
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            // Everything the entry imports goes in the entry chunk. Rolldown
            // otherwise gives each module shared with a lazy page its own
            // file, and the first page load preloads every one of them.
            {
              name: "app",
              tags: ["$initial"],
              priority: 2,
            },
            // The icon picker imports every icon on demand; one chunk instead
            // of one file per icon. Icons the entry uses stay in the entry.
            {
              name: "lucide-react",
              test: /\/lucide-react\//,
              priority: 1,
            },
          ],
        },
      },
    },
  },
  server: {
    // scripts/dev-ports.sh sets this per checkout so linked worktrees can run
    // side by side; a bare `pnpm dev` keeps the default.
    port: Number(process.env.VITE_DEV_PORT ?? 5173),
    strictPort: true,
    proxy: {
      // WebSocket endpoint needs explicit configuration
      "/api/v1/collaboration": {
        target: devProxyTarget,
        changeOrigin: true,
        ws: true,
        // Log proxy events for debugging
        configure: (proxy) => {
          proxy.on("error", (err) => {
            console.log("Proxy error:", err);
          });
          proxy.on("proxyReqWs", (proxyReq, req) => {
            console.log("Proxying WebSocket:", req.url);
          });
        },
      },
      "/api": createProxyConfig(true),
      "/uploads": createProxyConfig(),
    },
  },
});
