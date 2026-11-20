/**
 * Where this worker's bundle lands is part of its contract.
 *
 * The ratchet is vodozemac compiled to WebAssembly, and a worker carries the
 * Content-Security-Policy of the response that served its script rather than
 * the document's. The backend attaches a policy that admits WebAssembly by
 * matching the built file's path (`_WASM_WORKER_ASSET_PREFIXES` in
 * `backend/app/main.py`). Vite decides that path from two things — the worker
 * output pattern and this file's name — so both are pinned here, and the
 * backend pins the literal it matches. A rename on either side fails a test
 * rather than quietly serving a policy that refuses to compile the ratchet.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/** Keep in step with `_WASM_WORKER_ASSET_PREFIXES` in backend/app/main.py. */
const WORKER_OUTPUT = "assets/workers/[name]-[hash].js";

const resolve = (relative: string) => fileURLToPath(new URL(relative, import.meta.url));

describe("ratchet worker asset", () => {
  it("is emitted into the directory the backend matches", () => {
    const config = readFileSync(resolve("../../vite.config.ts"), "utf8");
    expect(config).toContain(`entryFileNames: "${WORKER_OUTPUT}"`);
  });

  it("is the entry the client starts", () => {
    const client = readFileSync(resolve("./client.ts"), "utf8");
    expect(client).toContain('new URL("./ratchet.worker.ts", import.meta.url)');
  });
});
