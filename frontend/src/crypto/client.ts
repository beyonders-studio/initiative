/**
 * The ratchet, as the rest of the app calls it.
 *
 * Every call crosses into a dedicated worker, and there is deliberately no path
 * that does not. Key material — including the pickle key, which the worker
 * reads from the store on its own side — therefore never enters the main
 * thread's realm.
 *
 * An earlier version fell back to calling the engine directly where `Worker`
 * was undefined. That is removed: a fallback is a second code path, and this
 * one would have held the key in exactly the realm the worker exists to keep it
 * out of. Somewhere without workers cannot have encrypted messages, and says so.
 *
 * Tests that exercise the ratchet itself import `./engine` directly.
 */

import type { RatchetMethod } from "./ratchet.worker";
import type {
  AccountCreated,
  Decrypted,
  Encrypted,
  InboundSession,
  KeysGenerated,
  OutboundSession,
  PreKeyInspected,
} from "./types";

type Pending = {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
};

let worker: Worker | null = null;
let nextId = 1;
const pending = new Map<number, Pending>();

class RatchetUnavailableError extends Error {
  constructor() {
    super("encrypted messages need a browser that supports web workers");
    this.name = "RatchetUnavailableError";
  }
}

/**
 * Whether this runtime can hold a ratchet at all.
 *
 * Three things are needed and any of them can be missing: a worker to run the
 * ratchet in, somewhere to keep the key store, and the browser's own crypto —
 * `subtle` for the key store and `randomUUID` for the names registrations and
 * messages carry. Both are only handed out on a secure origin, so a page served
 * over plain http from anything but localhost has neither. That is the common
 * one in development, and it looks like a broken feature rather than a wrong
 * address unless it is said out loud. `randomUUID` also arrived later than
 * `subtle` in some browsers (Safari 15.4), which are told the same.
 */
export function ratchetSupported(): boolean {
  return (
    typeof Worker !== "undefined" &&
    typeof indexedDB !== "undefined" &&
    typeof crypto !== "undefined" &&
    crypto.subtle !== undefined &&
    typeof crypto.randomUUID === "function"
  );
}

function ensureWorker(): Worker {
  if (typeof Worker === "undefined") throw new RatchetUnavailableError();
  if (worker === null) {
    worker = new Worker(new URL("./ratchet.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.onmessage = (event: MessageEvent<{ id: number; result?: unknown; error?: string }>) => {
      const entry = pending.get(event.data.id);
      if (!entry) return;
      pending.delete(event.data.id);
      if (event.data.error) entry.reject(new Error(event.data.error));
      else entry.resolve(event.data.result);
    };
  }
  return worker;
}

/**
 * Stop the worker and the pickle key it holds, for when the store is wiped. A
 * call still waiting on it is refused; the next call starts a fresh worker.
 */
export function stopRatchet(): void {
  if (worker === null) return;
  worker.terminate();
  worker = null;
  for (const entry of pending.values()) entry.reject(new Error("the ratchet was stopped"));
  pending.clear();
}

function call<T>(method: RatchetMethod, ...args: unknown[]): Promise<T> {
  let instance: Worker;
  try {
    instance = ensureWorker();
  } catch (error) {
    return Promise.reject(error);
  }
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
    instance.postMessage({ id, method, args });
  });
}

/**
 * The ratchet. No call takes a pickle key: the worker reads it on its own side,
 * so the one secret that opens a pickle never crosses a `postMessage`.
 */
export const ratchet = {
  createAccount: () => call<AccountCreated>("createAccount"),
  generateKeys: (pickle: string, count: number, withFallback: boolean) =>
    call<KeysGenerated>("generateKeys", pickle, count, withFallback),
  signDevice: (pickle: string, userId: number) => call<string>("signDevice", pickle, userId),
  verifyDevice: (userId: number, identityKey: string, fingerprintKey: string, signature: string) =>
    call<boolean>("verifyDevice", userId, identityKey, fingerprintKey, signature),
  createOutboundSession: (
    pickle: string,
    theirIdentityKey: string,
    theirFingerprintKey: string,
    theirOneTimeKey: string,
    oneTimeKeySignature: string,
    fallback: boolean
  ) =>
    call<OutboundSession>(
      "createOutboundSession",
      pickle,
      theirIdentityKey,
      theirFingerprintKey,
      theirOneTimeKey,
      oneTimeKeySignature,
      fallback
    ),
  inspectPreKey: (ciphertext: string) => call<PreKeyInspected | null>("inspectPreKey", ciphertext),
  createInboundSession: (pickle: string, theirIdentityKey: string, ciphertext: string) =>
    call<InboundSession | null>("createInboundSession", pickle, theirIdentityKey, ciphertext),
  encrypt: (sessionPickle: string, plaintext: string) =>
    call<Encrypted>("encrypt", sessionPickle, plaintext),
  decrypt: (sessionPickle: string, messageType: number, ciphertext: string) =>
    call<Decrypted | null>("decrypt", sessionPickle, messageType, ciphertext),
  verificationOpen: (txn: string) => call<string>("verificationOpen", txn),
  verificationEstablish: (txn: string, theirKey: string) =>
    call<void>("verificationEstablish", txn, theirKey),
  verificationEmoji: (txn: string, info: string) => call<number[]>("verificationEmoji", txn, info),
  verificationMac: (txn: string, input: string, info: string) =>
    call<string>("verificationMac", txn, input, info),
  verificationCheckMac: (txn: string, input: string, info: string, mac: string) =>
    call<boolean>("verificationCheckMac", txn, input, info, mac),
  verificationClose: (txn: string) => call<void>("verificationClose", txn),
  signVerification: (pickle: string, message: string) =>
    call<string>("signVerification", pickle, message),
  verifyVerification: (fingerprintKey: string, message: string, signature: string) =>
    call<boolean>("verifyVerification", fingerprintKey, message, signature),
};
