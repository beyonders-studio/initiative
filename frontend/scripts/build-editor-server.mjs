// Build the document editor for the server.
//
//   pnpm build:editor-server
//
// Writes dist-editor/editor.js: src/lib/yjs/serverEditor.ts and the editor it
// imports, as one script for the backend's embedded engine
// (backend/app/services/editor_worker.py). The libraries only the browser's
// views use are left out, and the browser globals the editor's modules read as
// they load are supplied by scripts/editor-server/prelude.js.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const STUB = join(ROOT, "scripts/editor-server/stub");
const VIEWS_ONLY = [
  "@excalidraw/excalidraw",
  "@excalidraw/mermaid-to-excalidraw",
  "mermaid",
  "katex",
];
const VERSION = readFileSync(join(ROOT, "../VERSION"), "utf8").trim();
const CLOUD_ORIGIN = readFileSync(join(ROOT, "../CLOUD_ORIGIN"), "utf8").trim();

await build({
  entryPoints: [join(ROOT, "src/lib/yjs/serverEditor.ts")],
  outfile: join(ROOT, "dist-editor/editor.js"),
  bundle: true,
  format: "iife",
  platform: "browser",
  // A package's worker build reads no `document`.
  conditions: ["worker"],
  minify: true,
  legalComments: "none",
  banner: { js: readFileSync(join(ROOT, "scripts/editor-server/prelude.js"), "utf8") },
  alias: {
    "@": join(ROOT, "src"),
    ...Object.fromEntries(VIEWS_ONLY.map((name) => [name, STUB])),
  },
  loader: {
    ".css": "empty",
    ".svg": "empty",
    ".png": "empty",
    ".woff2": "empty",
    ".wav": "empty",
    ".mp3": "empty",
  },
  define: {
    "process.env.NODE_ENV": '"production"',
    "import.meta.env": JSON.stringify({ MODE: "production", PROD: true, DEV: false }),
    __APP_VERSION__: JSON.stringify(VERSION),
    __CLOUD_ORIGIN__: JSON.stringify(CLOUD_ORIGIN),
    __IS_CAPACITOR__: "false",
    __EMOJIBASE_URL__: '""',
    __PDFJS_WORKER_URL__: '""',
    __PDFJS_WASM_URL__: '""',
  },
  logLevel: "error",
});
