/// <reference types="vite/client" />

declare const __APP_VERSION__: string;
/** Initiative Cloud's origin, from the CLOUD_ORIGIN file at the project root,
 *  which the backend reads too. */
declare const __CLOUD_ORIGIN__: string;
declare const __IS_CAPACITOR__: boolean;
/** Where the emoji picker fetches its dataset from — served by the app itself
 *  (see the emojibase plugin in vite.config.ts), never a public CDN. */
declare const __EMOJIBASE_URL__: string;
/** The pdf.js worker bundle, served by the app itself under `assets/workers/`
 *  so it gets the WebAssembly policy (see the pdfjs plugin in vite.config.ts). */
declare const __PDFJS_WORKER_URL__: string;
/** Directory the pdf.js worker fetches its WebAssembly image decoders from.
 *  Ends in a slash — pdf.js appends the bare filename. */
declare const __PDFJS_WASM_URL__: string;

// Vite's default client types cover common image/font asset URLs but not
// .wav. Declare it so `import url from "@/assets/foo.wav"` resolves to a
// hashed asset URL string at build time.
declare module "*.wav" {
  const src: string;
  export default src;
}

// Type declarations for Yjs-related packages
declare module "y-protocols/awareness" {
  import { Doc } from "yjs";

  export class Awareness {
    constructor(doc: Doc);
    clientID: number;
    getLocalState(): Record<string, unknown> | null;
    setLocalState(state: Record<string, unknown> | null): void;
    setLocalStateField(field: string, value: unknown): void;
    getStates(): Map<number, Record<string, unknown>>;
    on(event: "change" | "update", callback: (...args: unknown[]) => void): void;
    off(event: "change" | "update", callback: (...args: unknown[]) => void): void;
    destroy(): void;
  }

  /**
   * Encode awareness update for the given clients.
   * Used to broadcast cursor/selection state to other collaborators.
   */
  export function encodeAwarenessUpdate(awareness: Awareness, clients: number[]): Uint8Array;

  /**
   * Apply an awareness update received from another client.
   */
  export function applyAwarenessUpdate(
    awareness: Awareness,
    update: Uint8Array,
    origin: unknown
  ): void;
}
