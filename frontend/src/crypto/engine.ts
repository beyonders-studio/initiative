/**
 * The ratchet itself, as it runs inside the worker.
 *
 * Nothing here holds ratchet state between calls: every entry point takes the
 * pickles it needs and returns new ones. Those pickles are ciphertext, which is
 * why the main thread may hold them.
 *
 * The one exception is a verification between two of this account's devices,
 * which lives here for as long as the comparison does and is freed when it
 * ends; see `verificationOpen`.
 *
 * **The pickle key is fetched here, not passed in.** It is the one secret that
 * opens a pickle, and this module runs inside the worker — so the key is read
 * from the store on this side and never crosses a `postMessage`.
 */

import { pickleKey, whenDropped } from "./store";
import type {
  AccountCreated,
  Decrypted,
  Encrypted,
  InboundSession,
  KeysGenerated,
  OutboundSession,
  PreKeyInspected,
} from "./types";
import init, {
  create_account,
  create_inbound_session,
  create_outbound_session,
  generate_keys,
  inspect_prekey,
  session_decrypt,
  session_encrypt,
  sign_device,
  sign_verification,
  Verification,
  verify_device,
  verify_verification,
} from "./wasm/initiative_ratchet.js";

let ready: Promise<unknown> | null = null;

const isNode = typeof process !== "undefined" && process.versions?.node !== undefined;

/**
 * The pickle key, unwrapped once per worker rather than on every call. It is
 * kept only where a wipe of the store in any tab reaches this worker to clear
 * it; stopping the worker, which signing out does, clears it as well.
 */
let unwrapped: Promise<string> | null = null;

const keepable = whenDropped(() => {
  unwrapped = null;
});

function key(): Promise<string> {
  if (!keepable) return pickleKey();
  if (unwrapped === null) {
    const reading = pickleKey();
    unwrapped = reading;
    // A read that failed is not kept: the next call tries again.
    reading.catch(() => {
      if (unwrapped === reading) unwrapped = null;
    });
  }
  return unwrapped;
}

/**
 * Load the WebAssembly module once per context.
 *
 * In a browser the generated glue fetches the `.wasm` beside itself. Node has
 * nothing to fetch it from, so the bytes are read off disk and handed over —
 * which is only the test environment.
 */
export function loadRatchet(): Promise<unknown> {
  if (ready === null) {
    ready = isNode ? initFromDisk() : init();
  }
  return ready;
}

async function initFromDisk(): Promise<unknown> {
  const { readFile } = await import("node:fs/promises");
  const { resolve } = await import("node:path");
  // Resolved from the working directory rather than `import.meta.url`: under
  // the test runner that is an http: URL, which has no path to read.
  const path = resolve(process.cwd(), "src/crypto/wasm/initiative_ratchet_bg.wasm");
  return init({ module_or_path: await readFile(path) });
}

export async function createAccount(): Promise<AccountCreated> {
  await loadRatchet();
  return create_account(await key()) as AccountCreated;
}

export async function generateKeys(
  pickle: string,
  count: number,
  withFallback: boolean
): Promise<KeysGenerated> {
  await loadRatchet();
  return generate_keys(pickle, await key(), count, withFallback) as KeysGenerated;
}

export async function signDevice(pickle: string, userId: number): Promise<string> {
  await loadRatchet();
  return sign_device(pickle, await key(), userId);
}

export async function verifyDevice(
  userId: number,
  identityKey: string,
  fingerprintKey: string,
  signature: string
): Promise<boolean> {
  await loadRatchet();
  return verify_device(userId, identityKey, fingerprintKey, signature);
}

/**
 * Open a session with a device. The one-time key's signature is checked
 * against the fingerprint key inside the ratchet.
 */
export async function createOutboundSession(
  pickle: string,
  theirIdentityKey: string,
  theirFingerprintKey: string,
  theirOneTimeKey: string,
  oneTimeKeySignature: string,
  fallback: boolean
): Promise<OutboundSession> {
  await loadRatchet();
  return create_outbound_session(
    pickle,
    await key(),
    theirIdentityKey,
    theirFingerprintKey,
    theirOneTimeKey,
    oneTimeKeySignature,
    fallback
  ) as OutboundSession;
}

/*
 * Reading a message answers `null` where the ratchet itself refused it: it is
 * not a message this state can open, now or later. Everything else -- the key
 * store or the module failing to load -- still throws, so a caller can tell a
 * message that will never open from a moment when nothing could be opened.
 */

export async function inspectPreKey(ciphertext: string): Promise<PreKeyInspected | null> {
  await loadRatchet();
  try {
    return inspect_prekey(ciphertext) as PreKeyInspected;
  } catch {
    return null;
  }
}

export async function createInboundSession(
  pickle: string,
  theirIdentityKey: string,
  ciphertext: string
): Promise<InboundSession | null> {
  await loadRatchet();
  const pickleKey = await key();
  try {
    return create_inbound_session(
      pickle,
      pickleKey,
      theirIdentityKey,
      ciphertext
    ) as InboundSession;
  } catch {
    return null;
  }
}

export async function encrypt(sessionPickle: string, plaintext: string): Promise<Encrypted> {
  await loadRatchet();
  return session_encrypt(sessionPickle, await key(), plaintext) as Encrypted;
}

export async function decrypt(
  sessionPickle: string,
  messageType: number,
  ciphertext: string
): Promise<Decrypted | null> {
  await loadRatchet();
  const pickleKey = await key();
  try {
    return session_decrypt(sessionPickle, pickleKey, messageType, ciphertext) as Decrypted;
  } catch {
    return null;
  }
}

/** Sign one relayed verification message as this device's. */
export async function signVerification(pickle: string, message: string): Promise<string> {
  await loadRatchet();
  return sign_verification(pickle, await key(), message);
}

export async function verifyVerification(
  fingerprintKey: string,
  message: string,
  signature: string
): Promise<boolean> {
  await loadRatchet();
  return verify_verification(fingerprintKey, message, signature);
}

/** The comparisons in progress on this device, by attempt id. */
const verifications = new Map<string, Verification>();

function verification(txn: string): Verification {
  const open = verifications.get(txn);
  if (!open) throw new Error("no such verification");
  return open;
}

/** Start one side of a comparison: a fresh key pair, whose public half is returned. */
export async function verificationOpen(txn: string): Promise<string> {
  await loadRatchet();
  verificationClose(txn);
  const opened = new Verification();
  verifications.set(txn, opened);
  return opened.public_key;
}

export function verificationEstablish(txn: string, theirKey: string): void {
  verification(txn).establish(theirKey);
}

/** The pictures to show, as indices into the emoji list. */
export function verificationEmoji(txn: string, info: string): number[] {
  return Array.from(verification(txn).emoji(info));
}

export function verificationMac(txn: string, input: string, info: string): string {
  return verification(txn).mac(input, info);
}

export function verificationCheckMac(
  txn: string,
  input: string,
  info: string,
  mac: string
): boolean {
  return verification(txn).verify_mac(input, info, mac);
}

export function verificationClose(txn: string): void {
  verifications.get(txn)?.free();
  verifications.delete(txn);
}
