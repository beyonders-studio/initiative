/**
 * Where pdf.js lands, and what it is told to fetch, is part of its contract.
 *
 * pdf.js 6 decodes JBIG2, CCITT fax and JPEG 2000 images in WebAssembly — the
 * formats a scanned or faxed PDF is made of. Two things have to hold for that
 * to work, and neither is visible from the viewer component alone:
 *
 *  - The worker must be served with a policy that admits WebAssembly. A worker
 *    carries the Content-Security-Policy of the response that served its
 *    script, not the document's, and the backend picks those responses out by
 *    path (`_WASM_WORKER_ASSET_PREFIXES` in `backend/app/main.py`). So the
 *    build has to put pdf.js where the backend is looking.
 *  - The worker only loads the WebAssembly modules if `wasmUrl` names a
 *    directory holding them, and the build has to ship that directory.
 *
 * Both sides are literals in `vite.config.ts`, and the backend pins the one it
 * matches. A rename on either side fails a test here rather than quietly
 * serving policy that refuses to compile the decoders, or a viewer that renders
 * scanned pages blank.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/** Keep in step with `_WASM_WORKER_ASSET_PREFIXES` in backend/app/main.py. */
const WORKER_PREFIX = "assets/workers/pdf.worker-";

const resolve = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));

const viteConfig = readFileSync(resolve("../../../../vite.config.ts"), "utf8");
const viewer = readFileSync(resolve("./UploadedFileViewer.tsx"), "utf8");

describe("pdf.js assets", () => {
  it("emits the worker into the directory the backend matches", () => {
    // Asserted up to the version, which the build reads from the installed
    // pdfjs-dist: it stands in for the hash the bundled workers get, so a
    // browser can't hold a worker from one release beside modules from another.
    expect(viteConfig).toContain(`const PDFJS_WORKER_FILE = \`${WORKER_PREFIX}`);
  });

  it("emits the WebAssembly modules the worker fetches", () => {
    expect(viteConfig).toContain("const PDFJS_WASM_DIR = `assets/pdfjs-wasm/");
    // pdf.js appends the bare filename to the option, so the URL has to end in
    // a slash or the worker would ask for `.../6.3.289jbig2.wasm`.
    expect(viteConfig).toContain(`const PDFJS_WASM_URL = \`/\${PDFJS_WASM_DIR}/\`;`);
  });

  it("ships the legacy build, on all three of its pieces", () => {
    // pdf.js 6's default build calls `Map.prototype.getOrInsertComputed` — a
    // browser without it renders nothing at all, and most browsers in use are
    // without it. The legacy build is the same release carrying the polyfills.
    // The worker, the API react-pdf imports and the annotation/text layer have
    // to be the same build, so all three are asserted together.
    expect(viteConfig).toContain('path.join(PDFJS_DIR, "legacy/build/pdf.worker.min.mjs")');
    expect(viteConfig).toContain('path.join(PDFJS_DIR, "legacy/build/pdf.mjs")');
    expect(viteConfig).toContain('path.join(PDFJS_DIR, "legacy/web/pdf_viewer.mjs")');
    // Anchored: the other `pdfjs-dist/...` subpaths must still resolve normally.
    expect(viteConfig).toContain("find: /^pdfjs-dist$/");
  });

  it("points the viewer at both", () => {
    expect(viewer).toContain("pdfjs.GlobalWorkerOptions.workerSrc = __PDFJS_WORKER_URL__;");
    expect(viewer).toContain("const PDF_OPTIONS = { wasmUrl: __PDFJS_WASM_URL__ };");
    // Defined once at module scope and passed by identity: react-pdf reloads
    // the document whenever the options object changes.
    expect(viewer).toContain("options={PDF_OPTIONS}");
  });
});
