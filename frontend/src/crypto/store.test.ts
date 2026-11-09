/**
 * The two properties of the local store that keep messages.
 *
 * Both have been lost to a rebase more than once, and neither is visible to the
 * type checker or the linter: an append that clobbers another append still
 * compiles, and a session list that overwrites still compiles. So they are
 * asserted here.
 *
 * The atomicity has to live in an IndexedDB transaction: a JavaScript lock
 * would pass a race inside one module and still lose a message between two
 * windows. Each copy of this module holds one connection, as each tab does, so
 * the cross-tab race below imports a second copy.
 */

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { toBase64 } from "@/lib/base64";

import {
  accountPickle,
  claimOpen,
  deviceClaim,
  deviceId,
  deviceOwner,
  forgetDevice,
  messageLog,
  peerDeviceChanges,
  peerDeviceKeys,
  peerKeyChanges,
  pickleKey,
  serveAccount,
  sessionForDevice,
  sessionOrigin,
  sessionPickle,
  sessionsInConversation,
} from "./store";

beforeEach(async () => {
  await forgetDevice();
});

describe("the message log", () => {
  it("keeps both of two appends that race", async () => {
    // Sending and collecting are independently reachable and both append. A
    // plain read-modify-write loses whichever finishes first.
    await Promise.all([
      messageLog.append("conv", { id: "a", body: "first", at: "", mine: true }),
      messageLog.append("conv", { id: "b", body: "second", at: "", mine: false }),
    ]);

    const stored = await messageLog.get("conv");
    expect(stored.map((entry) => entry.id).sort()).toEqual(["a", "b"]);
  });

  it("keeps every message when many arrive at once, across connections", async () => {
    const messages = Array.from({ length: 12 }, (_, index) => ({
      id: String(index),
      body: `m${index}`,
      at: "",
      mine: false,
    }));

    // Two fresh copies, so both tabs read the same store: the copy the other
    // tests share keeps whichever account they served last, and empties only
    // that account's store before each test.
    vi.resetModules();
    const tab = await import("./store");
    vi.resetModules();
    const otherTab = await import("./store");
    await tab.forgetDevice();

    await Promise.all(
      messages.map((message, index) =>
        (index % 2 ? otherTab : tab).messageLog.append("conv", message)
      )
    );

    expect(await tab.messageLog.get("conv")).toHaveLength(12);
    // Deleting the database waits on every open connection; each lets go of
    // its own, and the next call opens afresh.
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.deleteDatabase("initiative-dm");
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("an open connection held the database"));
    });
    expect(await tab.messageLog.get("conv")).toEqual([]);
  });

  it("ignores a message it already holds", async () => {
    const message = { id: "a", body: "once", at: "", mine: true };
    await messageLog.append("conv", message);
    await messageLog.append("conv", message);

    expect(await messageLog.get("conv")).toHaveLength(1);
  });

  it("keeps conversations apart", async () => {
    await messageLog.append("one", { id: "a", body: "x", at: "", mine: true });
    await messageLog.append("two", { id: "b", body: "y", at: "", mine: true });

    expect(await messageLog.get("one")).toHaveLength(1);
    expect(await messageLog.get("two")).toHaveLength(1);
  });
});

describe("acting on a message already said", () => {
  const mine = { id: "m", body: "mine", at: "2026-01-01T00:00:00Z", mine: true };
  const theirs = { id: "t", body: "theirs", at: "2026-01-01T00:00:00Z", mine: false, author: 7 };

  beforeEach(async () => {
    await messageLog.append("conv", mine);
    await messageLog.append("conv", theirs);
  });

  it("counts both sides behind one emoji, and drops it when neither is", async () => {
    await messageLog.applyReaction("conv", "t", "🎲", true, "mine");
    await messageLog.applyReaction("conv", "t", "🎲", true, "theirs");

    let stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "t")?.reactions).toEqual({
      "🎲": { mine: true, theirs: true },
    });

    await messageLog.applyReaction("conv", "t", "🎲", false, "mine");
    await messageLog.applyReaction("conv", "t", "🎲", false, "theirs");

    stored = await messageLog.get("conv");
    // Not an emoji with nobody behind it: it stops being a reaction.
    expect(stored.find((entry) => entry.id === "t")?.reactions).toEqual({});
  });

  it("takes the same reaction twice as one", async () => {
    expect(await messageLog.applyReaction("conv", "t", "👍", true, "theirs")).toBe(true);
    // Both a tab that sent it and a tab that collected it can present it.
    expect(await messageLog.applyReaction("conv", "t", "👍", true, "theirs")).toBe(false);
  });

  it("lets each side rewrite only what it said", async () => {
    expect(
      await messageLog.applyEdit("conv", "m", "changed", "2026-01-02T00:00:00Z", "mine", 1)
    ).toBe(true);
    // Their envelope naming your message changes nothing, whatever it claims.
    expect(
      await messageLog.applyEdit("conv", "m", "hijacked", "2026-01-03T00:00:00Z", "theirs", 2)
    ).toBe(false);

    const stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "m")?.body).toBe("changed");
  });

  it("lets only the author rewrite what they said, on a roster", async () => {
    // Bob said it; Carol is on the same thread. Both arrive as "theirs", which
    // is why the side alone stopped being enough once a thread could hold more
    // than two people.
    await messageLog.append("group", {
      id: "b1",
      body: "bob said this",
      at: "2026-01-01T00:00:00Z",
      mine: false,
      author: 7,
    });

    expect(
      await messageLog.applyEdit(
        "group",
        "b1",
        "carol wrote this",
        "2026-01-02T00:00:00Z",
        "theirs",
        1,
        9
      )
    ).toBe(false);
    expect(await messageLog.applyRemove("group", "b1", "theirs", "2026-01-02T00:00:00Z", 9)).toBe(
      false
    );

    // Bob may, on his own message.
    expect(
      await messageLog.applyEdit(
        "group",
        "b1",
        "bob meant this",
        "2026-01-02T00:00:00Z",
        "theirs",
        1,
        7
      )
    ).toBe(true);
    const stored = await messageLog.get("group");
    expect(stored.find((entry) => entry.id === "b1")?.body).toBe("bob meant this");
  });

  it("lets the other side act only with an author to hold it to", async () => {
    // Their side always names who said it; an envelope that names nobody, or a
    // message that does, acts on nothing.
    await messageLog.append("old", {
      id: "o1",
      body: "said once",
      at: "2026-01-01T00:00:00Z",
      mine: false,
    });

    expect(
      await messageLog.applyEdit("old", "o1", "said twice", "2026-01-02T00:00:00Z", "theirs", 1, 7)
    ).toBe(false);
    expect(
      await messageLog.applyEdit("conv", "t", "said twice", "2026-01-02T00:00:00Z", "theirs", 1)
    ).toBe(false);
  });

  it("keeps the newest edit whichever order two arrive in", async () => {
    await messageLog.applyEdit("conv", "m", "second", "2026-01-03T00:00:00Z", "mine", 2);
    await messageLog.applyEdit("conv", "m", "first", "2026-01-02T00:00:00Z", "mine", 1);

    const stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "m")?.body).toBe("second");
  });

  it("orders edits by revision rather than by the device's clock", async () => {
    // Two devices of one account, clocks set independently: the correction
    // made second carries the earlier time, and losing to the one it was meant
    // to replace would leave the two of them holding different words forever.
    await messageLog.applyEdit("conv", "m", "typo", "2026-01-05T00:00:00Z", "mine", 1);
    await messageLog.applyEdit("conv", "m", "fixed", "2026-01-02T00:00:00Z", "mine", 2);

    const stored = await messageLog.get("conv");
    expect(stored.find((entry) => entry.id === "m")?.body).toBe("fixed");
  });

  it("settles two edits that reached the same revision the same way everywhere", async () => {
    // Arbitrary, but the same arbitrary answer on every device that sees both:
    // one that agrees beats a sensible one that does not.
    const order = async (first: string, second: string) => {
      await forgetDevice();
      await messageLog.append("conv", mine);
      await messageLog.applyEdit("conv", "m", first, "2026-01-02T00:00:00Z", "mine", 1);
      await messageLog.applyEdit("conv", "m", second, "2026-01-03T00:00:00Z", "mine", 1);
      return (await messageLog.get("conv")).find((entry) => entry.id === "m")?.body;
    };

    expect(await order("apple", "banana")).toBe(await order("banana", "apple"));
  });

  it("lets each side take back only what it said", async () => {
    expect(await messageLog.applyRemove("conv", "t", "mine", "2026-01-02T00:00:00Z")).toBe(false);
    expect(await messageLog.applyRemove("conv", "t", "theirs", "2026-01-02T00:00:00Z", 7)).toBe(
      true
    );

    // The entry stays, so a thread does not close over the gap.
    const stored = await messageLog.get("conv");
    expect(stored.map((entry) => entry.id)).toEqual(["m", "t"]);
    expect(stored[1]).toEqual({
      id: "t",
      at: "2026-01-01T00:00:00Z",
      mine: false,
      author: 7,
      replyTo: undefined,
      body: "",
      removedAt: "2026-01-02T00:00:00Z",
    });
  });

  it("takes the reactions and the receipt with it", async () => {
    await messageLog.applyReaction("conv", "t", "👍", true, "mine");
    await messageLog.applyRemove("conv", "t", "theirs", "2026-01-02T00:00:00Z", 7);

    const stored = await messageLog.get("conv");
    expect(stored[1].reactions).toBeUndefined();
  });

  it("leaves nothing to land on a message already taken back", async () => {
    await messageLog.applyRemove("conv", "t", "theirs", "2026-01-02T00:00:00Z", 7);

    expect(await messageLog.applyReaction("conv", "t", "👍", true, "mine")).toBe(false);
    expect(
      await messageLog.applyEdit("conv", "t", "back again", "2026-01-03T00:00:00Z", "theirs", 1, 7)
    ).toBe(false);
  });
});

describe("the sessions a conversation holds", () => {
  it("accumulates one per device rather than replacing", async () => {
    // The other party may have several devices, and each is its own ratchet.
    // Keeping one id per conversation makes the second device's messages
    // undecryptable.
    await sessionsInConversation.add("conv", "session-laptop");
    await sessionsInConversation.add("conv", "session-phone");

    expect(await sessionsInConversation.get("conv")).toEqual(["session-phone", "session-laptop"]);
  });

  it("does not list the same session twice", async () => {
    await sessionsInConversation.add("conv", "session-a");
    await sessionsInConversation.add("conv", "session-a");

    expect(await sessionsInConversation.get("conv")).toEqual(["session-a"]);
  });
});

describe("the account", () => {
  it("is replaced only by a writer that read what is stored", async () => {
    // The account holds the private half of every published prekey. Two tabs
    // advancing it from the same starting point — one collecting, one topping
    // up — would otherwise leave published keys with no private half.
    await accountPickle.set("first");

    expect(await accountPickle.swap("first", "second")).toBe(true);
    expect(await accountPickle.swap("first", "third")).toBe(false);
    expect(await accountPickle.get()).toBe("second");
  });

  it("admits exactly one of two writers that raced", async () => {
    await accountPickle.set("first");

    const results = await Promise.all([
      accountPickle.swap("first", "collected"),
      accountPickle.swap("first", "topped-up"),
    ]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it("keeps each account's store, so signing back in finds its messages", async () => {
    // A device keeps its store through a sign-out, so whoever signs in next may
    // be somebody else: another account, or the same id on another server.
    // Neither reads the first account's store, and neither empties it.
    const held = async () => (await messageLog.get("conv")).map((entry) => entry.body);

    serveAccount("https://one.example", 1);
    await messageLog.append("conv", { id: "a", body: "kept", at: "", mine: true });
    const key = await pickleKey();

    serveAccount("https://one.example", 2);
    expect(await held()).toEqual([]);
    expect(await deviceOwner.get()).toBe(2);
    await messageLog.append("conv", { id: "b", body: "theirs", at: "", mine: true });

    serveAccount("https://two.example", 1);
    expect(await held()).toEqual([]);

    serveAccount("https://one.example", 1);
    expect(await held()).toEqual(["kept"]);
    // One device key opens every account's store.
    expect(await pickleKey()).toBe(key);
    serveAccount("https://one.example", 2);
    expect(await held()).toEqual(["theirs"]);
  });

  it("keeps the keys a device already had when they move to their own database", async () => {
    // Before each account had its own store, the keys lived in the first one.
    // Its pickles are sealed with that pickle key, so a fresh one would leave
    // every message on the device unreadable.
    const wrap = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, [
      "encrypt",
      "decrypt",
    ]);
    const raw = crypto.getRandomValues(new Uint8Array(32));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const data = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, wrap, raw);
    const first = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open("initiative-dm", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("keys");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await new Promise<void>((resolve, reject) => {
      const transaction = first.transaction("keys", "readwrite");
      transaction.objectStore("keys").put(wrap, "wrap-key");
      transaction.objectStore("keys").put({ iv: iv.buffer, data }, "pickle-key");
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
    first.close();

    expect(await pickleKey()).toBe(toBase64(raw));
  });
});

describe("which side a session belongs to", () => {
  it("is remembered per session", async () => {
    await sessionOrigin.set("session-theirs", "other");
    await sessionOrigin.set("session-my-phone", "self");

    expect(await sessionOrigin.get("session-theirs")).toBe("other");
    expect(await sessionOrigin.get("session-my-phone")).toBe("self");
    expect(await sessionOrigin.get("session-unknown")).toBeUndefined();
  });
});

describe("the device-registration claim", () => {
  /** Past the window after which an abandoned claim may be taken over. */
  const STALE = 31_000;

  it("is taken by exactly one caller", async () => {
    // Two tabs opening Messages for the first time. Registering twice would
    // leave the server with two devices and this browser with one set of
    // private keys.
    const results = await Promise.all([deviceClaim.take(), deviceClaim.take(), deviceClaim.take()]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it("writes the keys, the id and the claim together", async () => {
    // One transaction: a tab that sees the claim settled must find everything
    // the device id refers to already there.
    const turn = await take();

    expect(await deviceClaim.settle(turn, "device-1", "pickle-1")).toBe(true);
    expect(await accountPickle.get()).toBe("pickle-1");
    expect(await deviceId.get()).toBe("device-1");
  });

  it("is not taken again once somebody has registered", async () => {
    const turn = await take();
    await deviceClaim.settle(turn, "device-1", "pickle-1");

    expect(await deviceClaim.take()).toBeNull();
    expect(await deviceClaim.read()).toEqual({ status: "ready", deviceId: "device-1" });
  });

  it("can be taken again by the next caller when one is handed back", async () => {
    // A tab that failed mid-registration must not hold the claim until it goes
    // stale, or the next attempt waits for nothing.
    const turn = await take();
    await deviceClaim.release(turn);

    expect(await deviceClaim.take()).not.toBeNull();
  });

  it("can be forced open when the recorded device is gone, taking what it held", async () => {
    const turn = await take();
    await deviceClaim.settle(turn, "device-1", "pickle-1");
    await messageLog.append("conv", { id: "a", body: "only here", at: "", mine: false });
    await deviceClaim.invalidate("device-1");

    // Removed from the account, so its keys and its messages go too.
    expect(await deviceId.get()).toBeUndefined();
    expect(await messageLog.get("conv")).toEqual([]);
    expect(await deviceClaim.take()).not.toBeNull();
  });

  it("leaves a claim somebody is already registering under alone", async () => {
    // One tab noticed the revocation first and is mid-registration. A second
    // tab reaching the same conclusion must wait for it, not reopen the claim
    // and register a competing device.
    const turn = await take();
    await deviceClaim.settle(turn, "device-1", "pickle-1");
    await deviceClaim.invalidate("device-1");
    expect(await deviceClaim.take()).not.toBeNull();

    await deviceClaim.invalidate("device-1");

    expect(await deviceClaim.take()).toBeNull();
  });

  it("is not reopened by a device other than the recorded one", async () => {
    const turn = await take();
    await deviceClaim.settle(turn, "device-2", "pickle-2");

    await deviceClaim.invalidate("device-1");

    expect(await deviceClaim.take()).toBeNull();
    expect(await deviceClaim.read()).toEqual({ status: "ready", deviceId: "device-2" });
    expect(await deviceId.get()).toBe("device-2");
  });

  it("cannot be settled by a caller whose turn was taken over", async () => {
    // A registration slower than the window the next tab waits out. Both
    // registered a device; only one set of private keys can be kept, and it has
    // to be the one belonging to the device the claim now names.
    const slow = await take();
    const quick = await afterStale(() => take());
    await deviceClaim.settle(quick, "device-quick", "pickle-quick");

    expect(await deviceClaim.settle(slow, "device-slow", "pickle-slow")).toBe(false);
    expect(await accountPickle.get()).toBe("pickle-quick");
    expect(await deviceId.get()).toBe("device-quick");
  });

  it("is not handed back by a caller whose turn was taken over", async () => {
    const slow = await take();
    const quick = await afterStale(() => take());

    await deviceClaim.release(slow);

    expect(await deviceClaim.take()).toBeNull();
    expect(await deviceClaim.read()).toMatchObject({ status: "claiming", token: quick });
  });

  it("reads as open once handed back or gone stale, and not while fresh or settled", async () => {
    expect(claimOpen(undefined)).toBe(true);
    const turn = await take();
    expect(claimOpen(await deviceClaim.read())).toBe(false);
    expect(await afterStale(async () => claimOpen(await deviceClaim.read()))).toBe(true);

    await deviceClaim.release(turn);
    expect(claimOpen(await deviceClaim.read())).toBe(true);

    await deviceClaim.settle(await take(), "device-1", "pickle-1");
    expect(await afterStale(async () => claimOpen(await deviceClaim.read()))).toBe(false);
  });

  /** Take the claim, failing the test rather than the assertion if it is held. */
  async function take(): Promise<string> {
    const turn = await deviceClaim.take();
    expect(turn).not.toBeNull();
    return turn as string;
  }

  /** Run something as though the stale window had passed. */
  async function afterStale<T>(work: () => Promise<T>): Promise<T> {
    const base = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(base + STALE);
    try {
      return await work();
    } finally {
      clock.mockRestore();
    }
  }
});

describe("remembered peer device keys", () => {
  it("says nothing about a key it is seeing for the first time", async () => {
    // Trust on first use. Warning here would warn on every new conversation,
    // which is how a warning stops being read.
    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    expect(changes).toEqual([]);
    expect(await peerDeviceKeys.all(7)).toEqual({
      "their-phone": { fingerprint: "fp-1", identityKey: "id-1" },
    });
  });

  it("reports a key that replaced one already used", async () => {
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: true }
    );

    // Both what it was and what it is now, so the change can be shown.
    expect(changes).toEqual([
      expect.objectContaining({
        userId: 7,
        deviceId: "their-phone",
        was: { fingerprint: "fp-1", identityKey: "id-1" },
        now: { fingerprint: "fp-2", identityKey: "id-2" },
      }),
    ]);
  });

  it("reports an encryption identity change when the displayed fingerprint is unchanged", async () => {
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "identity-1" }],
      { hold: true }
    );

    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "identity-2" }],
      { hold: true }
    );

    expect(changes).toEqual([
      expect.objectContaining({
        userId: 7,
        deviceId: "their-phone",
        now: { fingerprint: "fp-1", identityKey: "identity-2" },
      }),
    ]);
  });

  it("reports the same key only once", async () => {
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: true }
    );

    // The new key was remembered when it was reported. A second send must not
    // raise it again, or the notice never clears.
    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: true }
    );

    expect(changes).toEqual([]);
  });

  it("reports a new device id after a relationship is established", async () => {
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-laptop", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: true }
    );

    expect(changes).toEqual([
      expect.objectContaining({
        userId: 7,
        deviceId: "their-laptop",
        now: { fingerprint: "fp-2", identityKey: "id-2" },
      }),
    ]);
    // A new device has nothing it was.
    expect(changes[0]).not.toHaveProperty("was");
  });

  it("keeps one person's devices out of another's", async () => {
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "shared-id", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    const changes = await peerDeviceKeys.reconcile(
      8,
      [{ deviceId: "shared-id", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: true }
    );

    expect(changes).toEqual([]);
  });

  it("does not lose one device's change to another's, reconciling at once", async () => {
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "a", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );
    await peerDeviceKeys.reconcile(
      8,
      [{ deviceId: "b", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    // Two conversations sending at the same time is two tabs, and each opens
    // its own connection.
    const [first, second] = await Promise.all([
      peerDeviceKeys.reconcile(7, [{ deviceId: "a", fingerprint: "fp-2", identityKey: "id-2" }], {
        hold: true,
      }),
      peerDeviceKeys.reconcile(8, [{ deviceId: "b", fingerprint: "fp-2", identityKey: "id-2" }], {
        hold: true,
      }),
    ]);

    expect(first).toHaveLength(1);
    expect(second).toHaveLength(1);
  });

  it("holds the change in the same breath as recording the key", async () => {
    // The window this closes: reconcile writes the new fingerprint, and until
    // the hold is written too, a second send reconciling against that same
    // fingerprint finds nothing changed and nothing held -- so the device
    // reads as addressable and the message goes to the unacknowledged key.
    //
    // `await` is where that interleaving happens. Two sends in flight, or a
    // send and a background collection, are enough; nothing needs to be
    // running in parallel for the second to observe the gap.
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "their-phone", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: true }
    );
    expect(changes).toHaveLength(1);

    // Read as the racing send would, before the caller records anything.
    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).toContain("their-phone");

    // Another person's change is noted in the same transaction instead of held.
    await peerDeviceKeys.reconcile(
      8,
      [{ deviceId: "a", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: false }
    );
    await peerDeviceKeys.reconcile(
      8,
      [{ deviceId: "a", fingerprint: "fp-2", identityKey: "id-2" }],
      { hold: false }
    );
    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).not.toContain("a");
    expect((await peerDeviceChanges.all())[8]).toHaveLength(1);
  });

  it("leaves a first sighting unheld, so a new conversation is not interrupted", async () => {
    // The other direction. Trust-on-first-use is the design, and a hold
    // written here would fire on every new conversation.
    const changes = await peerDeviceKeys.reconcile(
      9,
      [{ deviceId: "first-seen", fingerprint: "fp-1", identityKey: "id-1" }],
      { hold: true }
    );

    expect(changes).toEqual([]);
    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).not.toContain("first-seen");
  });
});

describe("the list of changes waiting to be seen", () => {
  /** Hold a new device for each id: a baseline first, then the devices appearing. */
  const hold = async (userId: number, ...deviceIds: string[]) => {
    await peerDeviceKeys.reconcile(
      userId,
      [{ deviceId: "known", fingerprint: "fp-0", identityKey: "id-0" }],
      { hold: true }
    );
    await Promise.all(
      deviceIds.map((deviceId) =>
        peerDeviceKeys.reconcile(
          userId,
          [{ deviceId, fingerprint: `fp-${deviceId}`, identityKey: `id-${deviceId}` }],
          { hold: true }
        )
      )
    );
  };

  it("holds one entry per device, newest winning", async () => {
    await hold(7, "a");
    await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "a", fingerprint: "fp-3", identityKey: "id-3" }],
      { hold: true }
    );

    const held = await peerKeyChanges.all();
    expect(held).toHaveLength(1);
    expect(held[0]?.now.fingerprint).toBe("fp-3");
  });

  it("keeps both of two holds that race", async () => {
    await hold(7, "a", "b");

    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId).sort()).toEqual(["a", "b"]);
  });

  it("clears only the devices acknowledged", async () => {
    await hold(7, "a", "b");
    await peerKeyChanges.markAsked(["b"]);

    await peerKeyChanges.acknowledge(["a"]);

    const [left] = await peerKeyChanges.all();
    expect(left).toMatchObject({ deviceId: "b", asked: true });
    await peerKeyChanges.acknowledge(["b"]);
    expect(await peerKeyChanges.all()).toEqual([]);
  });

  /** A listing asked for after every hold so far was raised. */
  const later = () => Date.now() + 1_000;

  it("lets go of a device the account no longer lists", async () => {
    await hold(7, "a", "b");

    await peerKeyChanges.withdrawUnlisted(7, ["known", "b"], later());

    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).toEqual(["b"]);
  });

  it("leaves other accounts' holds alone", async () => {
    await hold(7, "a");
    await hold(8, "c");

    await peerKeyChanges.withdrawUnlisted(7, ["known"], later());

    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).toEqual(["c"]);
  });

  it("keeps a hold raised after the listing was asked for", async () => {
    // Another tab held a device too new for this tab's listing, and is about
    // to read that hold to decide what it may send to.
    const asked = Date.now() - 1_000;
    await hold(7, "a");

    await peerKeyChanges.withdrawUnlisted(7, ["known"], asked);

    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).toEqual(["a"]);
    expect(
      await peerDeviceKeys.reconcile(
        7,
        [{ deviceId: "a", fingerprint: "fp-a", identityKey: "id-a" }],
        { hold: true }
      )
    ).toEqual([]);
  });

  it("asks again about a withdrawn device that is listed after all", async () => {
    await hold(7, "a");
    await peerKeyChanges.withdrawUnlisted(7, ["known"], later());

    const changes = await peerDeviceKeys.reconcile(
      7,
      [{ deviceId: "a", fingerprint: "fp-a", identityKey: "id-a" }],
      { hold: true }
    );

    expect(changes.map((change) => change.deviceId)).toEqual(["a"]);
    expect((await peerKeyChanges.all()).map((entry) => entry.deviceId)).toEqual(["a"]);
  });
});

describe("the session filed against a device", () => {
  it("stops being chosen once it is forgotten", async () => {
    // A session is filed by device id, and a device id outlives the key it was
    // opened against. When the key changes the session in hand can no longer
    // be read by the far end, so it must not be the one the next send picks.
    await sessionForDevice.set("their-phone", "session-1");
    expect(await sessionForDevice.get("their-phone")).toBe("session-1");

    await sessionForDevice.forget("their-phone");

    expect(await sessionForDevice.get("their-phone")).toBeUndefined();
  });

  it("leaves other devices alone", async () => {
    await sessionForDevice.set("their-phone", "session-1");
    await sessionForDevice.set("their-laptop", "session-2");

    await sessionForDevice.forget("their-phone");

    expect(await sessionForDevice.get("their-laptop")).toBe("session-2");
  });

  it("keeps the pickle, which other conversations still file", async () => {
    // Dropping the pointer is enough to stop the session being chosen. The
    // pickle is shared, and deleting it would reach into conversations this
    // change is not about.
    await sessionPickle.set("session-1", "pickle-bytes");
    await sessionForDevice.set("their-phone", "session-1");

    await sessionForDevice.forget("their-phone");

    expect(await sessionPickle.get("session-1")).toBe("pickle-bytes");
  });
});
