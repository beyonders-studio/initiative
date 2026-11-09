/**
 * The ratchet, end to end.
 *
 * This is the test that matters for the whole feature: two accounts that have
 * never met derive a shared session from published keys alone, and what one
 * sends the other can read. If this passes, the server is carrying bytes it
 * cannot open.
 */

import { describe, expect, it, vi } from "vitest";

// The worker reads the pickle key from the store on its own side, and there is
// no IndexedDB here — so the store is stubbed with a fixed key. The ratchet
// under test is entirely real.
const store = vi.hoisted(() => ({
  pickleKey: vi.fn(async () => btoa(String.fromCharCode(...new Uint8Array(32).fill(7)))),
  dropped: () => {},
}));
vi.mock("./store", () => ({
  pickleKey: () => store.pickleKey(),
  whenDropped: (listener: () => void) => {
    store.dropped = listener;
    return true;
  },
}));

// The engine, not the client: the client only speaks to a worker, and what is
// under test here is the ratchet rather than the transport that reaches it.
import * as ratchet from "./engine";

describe("the double ratchet", () => {
  it("carries a message between two accounts that never exchanged a secret", async () => {
    const alice = await ratchet.createAccount();
    const bob = await ratchet.createAccount();

    // Bob publishes prekeys; Alice claims one from the directory.
    const bobKeys = await ratchet.generateKeys(bob.pickle, 5, true);
    const claimed = bobKeys.one_time_keys[0];

    const outbound = await ratchet.createOutboundSession(
      alice.pickle,
      bob.identity_key,
      bob.fingerprint_key,
      claimed.public_key,
      claimed.signature,
      false
    );
    const sent = await ratchet.encrypt(outbound.session_pickle, "the server cannot read this");
    expect(sent.message_type).toBe(0);

    const inbound = await ratchet.createInboundSession(
      bobKeys.pickle,
      alice.identity_key,
      sent.ciphertext
    );
    expect(inbound?.plaintext).toBe("the server cannot read this");
  });

  it("keeps the conversation going after the session is established", async () => {
    const alice = await ratchet.createAccount();
    const bob = await ratchet.createAccount();
    const bobKeys = await ratchet.generateKeys(bob.pickle, 5, true);

    const outbound = await ratchet.createOutboundSession(
      alice.pickle,
      bob.identity_key,
      bob.fingerprint_key,
      bobKeys.one_time_keys[0].public_key,
      bobKeys.one_time_keys[0].signature,
      false
    );
    const first = await ratchet.encrypt(outbound.session_pickle, "one");
    const inbound = await ratchet.createInboundSession(
      bobKeys.pickle,
      alice.identity_key,
      first.ciphertext
    );

    // Bob answers on the session the pre-key message established.
    if (!inbound) throw new Error("the pre-key message did not open");
    const reply = await ratchet.encrypt(inbound.session_pickle, "two");
    const read = await ratchet.decrypt(first.session_pickle, reply.message_type, reply.ciphertext);
    expect(read?.plaintext).toBe("two");
  });

  it("publishes a reusable fallback key alongside the pool", async () => {
    store.dropped();
    store.pickleKey.mockClear();
    const account = await ratchet.createAccount();
    const keys = await ratchet.generateKeys(account.pickle, 3, true);

    expect(keys.one_time_keys).toHaveLength(3);
    expect(keys.fallback_key).not.toBeNull();
    // The pickle key is unwrapped once per worker, and again once the store is
    // wiped from any tab.
    expect(store.pickleKey).toHaveBeenCalledTimes(1);
    store.dropped();
    await ratchet.generateKeys(account.pickle, 1, false);
    expect(store.pickleKey).toHaveBeenCalledTimes(2);
  });

  it("signs a device and its keys, and checks both", async () => {
    const alice = await ratchet.createAccount();
    const bob = await ratchet.createAccount();
    const bobKeys = await ratchet.generateKeys(bob.pickle, 1, true);
    const signature = await ratchet.signDevice(bobKeys.pickle, 7);

    // The signature binds the keys to the account they are listed under.
    expect(await ratchet.verifyDevice(7, bob.identity_key, bob.fingerprint_key, signature)).toBe(
      true
    );
    expect(await ratchet.verifyDevice(8, bob.identity_key, bob.fingerprint_key, signature)).toBe(
      false
    );
    expect(await ratchet.verifyDevice(7, alice.identity_key, bob.fingerprint_key, signature)).toBe(
      false
    );

    // A one-time key is taken only with its own signature; the fallback's is
    // made over its own tag, so it does not stand in for a one-time key's.
    const [oneTime] = bobKeys.one_time_keys;
    const fallback = bobKeys.fallback_key!;
    await expect(
      ratchet.createOutboundSession(
        alice.pickle,
        bob.identity_key,
        bob.fingerprint_key,
        oneTime.public_key,
        fallback.signature,
        false
      )
    ).rejects.toThrow();
    // Nor is one taken with no signature at all, however it is missing.
    for (const missing of ["", null, undefined]) {
      await expect(
        ratchet.createOutboundSession(
          alice.pickle,
          bob.identity_key,
          bob.fingerprint_key,
          oneTime.public_key,
          missing as unknown as string,
          false
        )
      ).rejects.toThrow();
    }
    const opened = await ratchet.createOutboundSession(
      alice.pickle,
      bob.identity_key,
      bob.fingerprint_key,
      fallback.public_key,
      fallback.signature,
      true
    );

    // A pre-key message names its session and its sender without being opened.
    const sent = await ratchet.encrypt(opened.session_pickle, "hello");
    expect(await ratchet.inspectPreKey(sent.ciphertext)).toEqual({
      session_id: opened.session_id,
      identity_key: alice.identity_key,
    });
  });

  it("answers null for what it refuses to read", async () => {
    // A refusal is an answer, not a failure: it is what lets a caller drop a
    // message that will never open rather than retry it forever.
    expect(await ratchet.decrypt("not-a-pickle", 1, "AAAA")).toBeNull();
    expect(await ratchet.inspectPreKey("AAAA")).toBeNull();
    const bob = await ratchet.createAccount();
    expect(await ratchet.createInboundSession(bob.pickle, bob.identity_key, "AAAA")).toBeNull();
  });
});
