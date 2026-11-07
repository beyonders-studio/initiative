import { tanStackRouterCodeSplitter } from "@tanstack/router-plugin/vite";
import path from "path";
import { defineConfig } from "vitest/config";

// The app formats dates and numbers in the runtime's own locale, and the
// tests expect English. Each test worker is a child process, which takes its
// locale from this when it starts.
process.env.LC_ALL = "en_US.UTF-8";

export default defineConfig({
  // A route's page loads with the route, as in the build, so importing the
  // route tree does not load every page.
  plugins: [tanStackRouterCodeSplitter()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  define: {
    __APP_VERSION__: JSON.stringify("0.0.0-test"),
    __IS_CAPACITOR__: JSON.stringify(false),
    // The app serves its own emoji dataset rather than reaching a CDN, and the
    // path is a build-time constant. Without it here the identifier survives
    // into the test bundle and any component that opens the picker throws.
    __EMOJIBASE_URL__: JSON.stringify("/emojibase"),
    // Likewise for the self-hosted pdf.js worker and its WebAssembly image
    // decoders: the identifiers are build-time constants, and the PDF viewer
    // reads both at module scope.
    __PDFJS_WORKER_URL__: JSON.stringify("/assets/workers/pdf.worker-test.mjs"),
    __PDFJS_WASM_URL__: JSON.stringify("/assets/pdfjs-wasm/test/"),
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    css: false,
    // Tests must be hermetic: a developer's frontend/.env (VITE_API_URL)
    // would otherwise make apiClient requests absolute, bypassing MSW's
    // relative handlers.
    env: { VITE_API_URL: "" },
    // Headroom over the 5s default: with every worker transforming the app's
    // heavy import graphs in parallel, userEvent-driven dialog tests can sit
    // queued for seconds on slower dev machines and time out spuriously while
    // passing in isolation. CI finishes comfortably under either ceiling.
    testTimeout: 15_000,
    // Whatever a test swaps in is put back when it ends: a spy, a global, an
    // environment variable. A test that needs one across tests sets it in a
    // beforeEach.
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
  },
});
