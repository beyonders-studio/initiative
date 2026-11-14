/* tslint:disable */
/* eslint-disable */

/**
 * One comparison between two of an account's devices.
 *
 * Each side makes a fresh key pair, swaps public halves with the other, and
 * both derive the same few pictures from the shared secret. Nothing here is
 * derived from the device's long-lived keys, so every comparison shows
 * different pictures. The long-lived keys are then vouched for with MACs under
 * the same shared secret, once the person says the pictures match.
 */
export class Verification {
    free(): void;
    [Symbol.dispose](): void;
    /**
     * The pictures to show, as indices into the 64-emoji list.
     */
    emoji(info: string): Uint8Array;
    /**
     * Derive the shared secret from the other side's public key. Once only.
     */
    establish(their_key: string): void;
    mac(input: string, info: string): string;
    constructor();
    verify_mac(input: string, info: string, mac: string): boolean;
    /**
     * This side's public key for this comparison.
     */
    readonly public_key: string;
}

/**
 * Generate this device's long-lived identity.
 *
 * The private halves exist only inside the returned pickle, which is already
 * encrypted under `key`.
 */
export function create_account(key: string): any;

/**
 * Answer a pre-key message by deriving the session it describes.
 *
 * The account changes too: the prekey it spent is forgotten, so the same
 * message cannot open a second session.
 */
export function create_inbound_session(pickle: string, key: string, their_identity_key: string, ciphertext: string): any;

/**
 * Open a session with a device, spending a prekey claimed from the directory.
 *
 * The prekey's signature must verify against the device's fingerprint key.
 */
export function create_outbound_session(pickle: string, key: string, their_identity_key: string, their_fingerprint_key: string, their_one_time_key: string, one_time_key_signature: string, fallback: boolean): any;

/**
 * Top the prekey pool up, and mint a fallback key if asked.
 *
 * The fallback key is reusable and is what a sender gets when the pool is
 * drained, so a device that has been quiet for a long time stays reachable.
 */
export function generate_keys(pickle: string, key: string, count: number, with_fallback: boolean): any;

/**
 * Which session a pre-key message opens, and who sent it, without opening it.
 */
export function inspect_prekey(ciphertext: string): any;

/**
 * Decrypt one message, advancing the ratchet.
 */
export function session_decrypt(pickle: string, key: string, message_type: number, ciphertext: string): any;

/**
 * Encrypt one message, advancing the ratchet.
 */
export function session_encrypt(pickle: string, key: string, plaintext: string): any;

/**
 * Sign this device's keys as belonging to `user_id`.
 */
export function sign_device(pickle: string, key: string, user_id_value: number): string;

/**
 * Sign one relayed verification message as this device's.
 */
export function sign_verification(pickle: string, key: string, message: string): string;

/**
 * Whether a directory entry's keys were signed, by its own fingerprint key,
 * as belonging to `user_id`.
 */
export function verify_device(user_id_value: number, identity_key: string, fingerprint_key: string, signature: string): boolean;

/**
 * Whether a relayed verification message was signed by the device whose
 * fingerprint key the directory lists.
 */
export function verify_verification(fingerprint_key: string, message: string, signature: string): boolean;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly __wbg_verification_free: (a: number, b: number) => void;
    readonly create_account: (a: number, b: number) => [number, number, number];
    readonly create_inbound_session: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number) => [number, number, number];
    readonly create_outbound_session: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number, j: number, k: number, l: number, m: number) => [number, number, number];
    readonly generate_keys: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number];
    readonly inspect_prekey: (a: number, b: number) => [number, number, number];
    readonly session_decrypt: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => [number, number, number];
    readonly session_encrypt: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number];
    readonly sign_device: (a: number, b: number, c: number, d: number, e: number) => [number, number, number, number];
    readonly sign_verification: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number, number];
    readonly verification_emoji: (a: number, b: number, c: number) => [number, number, number, number];
    readonly verification_establish: (a: number, b: number, c: number) => [number, number];
    readonly verification_mac: (a: number, b: number, c: number, d: number, e: number) => [number, number, number, number];
    readonly verification_new: () => number;
    readonly verification_public_key: (a: number) => [number, number];
    readonly verification_verify_mac: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => [number, number, number];
    readonly verify_device: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => [number, number, number];
    readonly verify_verification: (a: number, b: number, c: number, d: number, e: number, f: number) => [number, number, number];
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
