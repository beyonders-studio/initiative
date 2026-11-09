/**
 * What the client does around the ratchet.
 *
 * The ratchet itself is proved in `ratchet.test.ts` against the real
 * implementation. What is on trial here is the orchestration: which side of a
 * thread a collected message lands on, when a prekey is spent, and what happens
 * when there is nobody to deliver to. None of that is visible to the type
 * checker — a message attributed to the wrong person still compiles.
 */

import "fake-indexeddb/auto";

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DmSendRequest } from "@/api/generated/initiativeAPI.schemas";

/** Prekeys the stand-in account has already spent. Cleared per test. */
const spent = vi.hoisted(() => new Set<string>());

const api = vi.hoisted(() => ({
  listDevices: vi.fn(),
  readDirectory: vi.fn(),
  claimSessionKeys: vi.fn(),
  claimOwnSessionKeys: vi.fn(),
  sendMessages: vi.fn<(conversationId: string, body: DmSendRequest) => Promise<unknown>>(),
  collectQueue: vi.fn(),
  ackQueue: vi.fn(),
  listConversations: vi.fn(),
  registerDevice: vi.fn(),
  removeDevice: vi.fn(),
  topUpKeys: vi.fn(),
  readMe: vi.fn(),
  sendVerification: vi.fn(),
  collectVerification: vi.fn(),
}));

vi.mock("@/api/generated/direct-messages/direct-messages", () => ({
  listDevices: () => api.listDevices(),
  readDirectory: (userId: number) => api.readDirectory(userId),
  claimSessionKeys: (userId: number, body: unknown) => api.claimSessionKeys(userId, body),
  claimOwnSessionKeys: (body: unknown) => api.claimOwnSessionKeys(body),
  sendMessages: (id: string, body: DmSendRequest) => api.sendMessages(id, body),
  collectQueue: (params: unknown) => api.collectQueue(params),
  acknowledgeQueue: (body: unknown) => api.ackQueue(body),
  listConversations: () => api.listConversations(),
  registerDevice: (body: unknown) => api.registerDevice(body),
  removeDevice: (id: string) => api.removeDevice(id),
  topUpKeys: (body: unknown) => api.topUpKeys(body),
  sendVerification: (body: unknown) => api.sendVerification(body),
  collectVerification: (params: unknown) => api.collectVerification(params),
}));

vi.mock("@/api/generated/users/users", () => ({
  readMe: () => api.readMe(),
}));

/**
 * A stand-in ratchet whose ciphertext names its sender.
 *
 * The real one refuses an identity key that did not write the message, and a
 * pre-key message names its session and sender; this reproduces those rules
 * and nothing else. A device's signature is `signed:<its account>`.
 *
 * Verification is the real one: its whole point is the arithmetic, so a
 * stand-in would prove nothing.
 */
const stopRatchet = vi.hoisted(() => vi.fn());
const openOutbound = vi.hoisted(() =>
  vi.fn(async (_pickle: string, identity: string, ..._rest: unknown[]) => ({
    session_pickle: `session:${identity}`,
    session_id: `session:${identity}`,
  }))
);

vi.mock("./client", () => ({
  stopRatchet,
  ratchet: {
    createAccount: async () => ({ pickle: "account", identity_key: "mine", fingerprint_key: "fp" }),
    generateKeys: async (pickle: string, count: number, withFallback: boolean) => ({
      pickle: `${pickle}+${count}`,
      one_time_keys: Array.from({ length: count }, (_, index) => ({
        key_id: `k${index}`,
        public_key: `pk${index}`,
        signature: `otk-signed${index}`,
      })),
      fallback_key: withFallback
        ? { key_id: "fb", public_key: "fbpk", signature: "fallback-signed" }
        : null,
    }),
    signDevice: async (_pickle: string, userId: number) => `signed:${userId}`,
    verifyDevice: async (userId: number, _identity: string, _fp: string, signature: string) =>
      signature === `signed:${userId}`,
    createOutboundSession: openOutbound,
    inspectPreKey: async (ciphertext: string) => {
      const message = JSON.parse(ciphertext);
      return { session_id: `session:${message.from}`, identity_key: message.from };
    },
    // Refusals answer `null`, as the real engine's do.
    createInboundSession: async (pickle: string, identity: string, ciphertext: string) => {
      const message = JSON.parse(ciphertext);
      if (message.from !== identity) return null;
      // A prekey opens exactly one session: the real account forgets the one it
      // just spent, so the same pre-key message cannot open a second.
      if (message.prekey) {
        if (spent.has(message.prekey)) return null;
        spent.add(message.prekey);
      }
      return {
        account_pickle: `${pickle}-spent`,
        session_pickle: `session:${identity}`,
        session_id: `session:${identity}`,
        plaintext: message.body,
      };
    },
    // Both ends of a ratchet move on with every message. The "!" is that step,
    // so a lost one is visible in the stored pickle.
    encrypt: async (sessionPickle: string, plaintext: string) => ({
      session_pickle: `${sessionPickle}!`,
      message_type: 1,
      ciphertext: JSON.stringify({ from: "mine", body: plaintext }),
    }),
    decrypt: async (sessionPickle: string, _type: number, ciphertext: string) => {
      const message = JSON.parse(ciphertext);
      if (!sessionPickle.startsWith(`session:${message.from}`)) return null;
      return { session_pickle: `${sessionPickle}!`, plaintext: message.body };
    },
    verificationOpen: async (txn: string) => (await import("./engine")).verificationOpen(txn),
    verificationEstablish: async (txn: string, key: string) =>
      (await import("./engine")).verificationEstablish(txn, key),
    verificationEmoji: async (txn: string, info: string) =>
      (await import("./engine")).verificationEmoji(txn, info),
    verificationMac: async (txn: string, input: string, info: string) =>
      (await import("./engine")).verificationMac(txn, input, info),
    verificationCheckMac: async (txn: string, input: string, info: string, mac: string) =>
      (await import("./engine")).verificationCheckMac(txn, input, info, mac),
    verificationClose: async (txn: string) => (await import("./engine")).verificationClose(txn),
    // A relayed message is signed by the device that sent it: `signed:<text>`.
    signVerification: async (_pickle: string, message: string) => `signed:${message}`,
    verifyVerification: async (_fingerprint: string, message: string, signature: string) =>
      signature === `signed:${message}`,
  },
}));

import { ratchet } from "./client";
import * as engine from "./engine";
import {
  answerNewDevice,
  collect,
  collectVerification,
  confirmMatch,
  ensureDevice,
  forgetMessagesOnThisDevice,
  HISTORY_ASK_NOTICE_MS,
  historyAskWaiting,
  markRead,
  ownDeviceWaiting,
  peerDeviceChanges,
  RecipientHasNoDeviceError,
  sendEdit,
  sendReaction,
  sendRemove,
  sendText,
  startVerification,
  unreadIn,
  verificationView,
  wantThreadHistory,
} from "./messaging";
import { emojiAt } from "./safetyCode";
import {
  accountPickle,
  approvedDevices,
  deviceClaim,
  deviceId,
  deviceOwner,
  forgetDevice,
  historyAsk,
  messageLog,
  peerKeyChanges,
  sessionPickle,
  threadCatchUp,
} from "./store";

// Registration order matters: an ask only travels from a newer device to an
// older one, so the browser under test is the one that arrived second and the
// phone is the established device holding the history.
const OURS = { id: "device-1", identity_key: "mine", created_at: "2026-09-01T00:00:00Z" };
const OUR_PHONE = { id: "device-2", identity_key: "phone", created_at: "2026-08-01T00:00:00Z" };
const THEIRS = {
  device_id: "device-9",
  identity_key: "theirs",
  fingerprint_key: "fp",
  signature: "signed:7",
};

const ownDevice = (
  device: { id: string; identity_key: string; created_at?: string; signature?: string | null },
  keysHeld = 50
) => ({
  fingerprint_key: "fp",
  label: null,
  created_at: "2026-09-01T00:00:00Z",
  last_seen_at: "2026-09-01T00:00:00Z",
  one_time_key_count: keysHeld,
  signature: "signed:1",
  ...device,
});

/** A one-time key as the claim endpoint hands it back, signed by its device. */
const ONE_TIME_KEY = { key_id: "k", public_key: "pk", signature: "otk-signed" };

/** One device's claimable prekey, as the claim endpoint hands it back. */
const keyFor = (device: { id: string; identity_key: string }) => ({
  device_id: device.id,
  identity_key: device.identity_key,
  fingerprint_key: "fp",
  one_time_key: ONE_TIME_KEY,
});

const queued = (overrides: Record<string, unknown>) => ({
  id: 1,
  conversation_id: "conv-1",
  message_type: 0,
  created_at: "2026-09-01T00:00:00Z",
  ...overrides,
});

const from = (identity: string, body: string, prekey?: string) =>
  JSON.stringify({ from: identity, body, prekey });

beforeEach(async () => {
  await forgetDevice();
  spent.clear();
  vi.clearAllMocks();
  // Signing in records the account before anything reads the store.
  await deviceOwner.set(1);
  // A device that is already registered: the registration path has its own
  // tests, and every case here starts after it.
  await deviceId.set(OURS.id);
  await accountPickle.set("account");
  // A device whose question about its own history has been settled. The asking
  // has its own tests below; everything else here starts after it.
  await historyAsk.close();
  api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS), ownDevice(OUR_PHONE)] });
  api.readDirectory.mockResolvedValue({ user_id: 7, devices: [THEIRS] });
  api.claimSessionKeys.mockResolvedValue({
    user_id: 7,
    devices: [{ ...THEIRS, one_time_key: ONE_TIME_KEY }],
  });
  api.claimOwnSessionKeys.mockResolvedValue({ user_id: 1, devices: [keyFor(OUR_PHONE)] });
  api.listConversations.mockResolvedValue({
    conversations: [
      { id: "conv-1", other_user_id: 7, member_ids: [7], created_at: "2026-09-01T00:00:00Z" },
    ],
  });
  api.collectQueue.mockResolvedValue({ items: [] });
  api.sendMessages.mockResolvedValue(undefined);
  api.ackQueue.mockResolvedValue(undefined);
  api.topUpKeys.mockResolvedValue({ devices: [] });
  api.readMe.mockResolvedValue({ id: 1 });
});

describe("collecting", () => {
  it("puts a message from the other party on their side of the thread", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "how are you") })],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "how are you", mine: false }),
    ]);
  });

  it("puts a message from this account's own device on this side", async () => {
    // The outbox arriving from another client of the same account. It carries
    // no sender, and attributing it to the other party would show somebody
    // their own words as if they had been written to them.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("phone", "sent from the phone") })],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "sent from the phone", mine: true }),
    ]);
  });

  it("keeps an ordinary message on the side its session belongs to", async () => {
    // Only the first message of a session names an identity. Everything after
    // it is read on the session, so which side it belongs to has to have been
    // written down when the session was opened.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, payload: from("phone", "first") }),
        queued({ id: 2, message_type: 1, payload: from("phone", "second") }),
      ],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "first", mine: true }),
      expect.objectContaining({ body: "second", mine: true }),
    ]);
  });

  it("reads a directory only for conversations a pre-key message arrived in", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ message_type: 1, payload: from("theirs", "ordinary") })],
    });

    await collect();

    expect(api.readDirectory).not.toHaveBeenCalled();
  });

  it("reads an ordinary message on a session opened in another conversation", async () => {
    // One device is in every conversation this account has — its own other
    // clients are — so the session it opened in one carries messages in the
    // next. A message that finds no session is never readable again.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("phone", "opened here") })],
    });
    await collect();

    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 2,
          conversation_id: "conv-2",
          message_type: 1,
          payload: from("phone", "carried on"),
        }),
      ],
    });
    await collect();

    expect(await messageLog.get("conv-2")).toEqual([
      expect.objectContaining({ body: "carried on", mine: true }),
    ]);

    // Somebody else's session is tried only where they are on the roster: a
    // message in a conversation they are not on is not theirs to carry.
    api.collectQueue.mockResolvedValue({
      items: [queued({ id: 3, payload: from(THEIRS.identity_key, "opened", "otk-1") })],
    });
    await collect({ receipts: false });
    api.ackQueue.mockClear();
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 4,
          conversation_id: "conv-2",
          message_type: 1,
          payload: from(THEIRS.identity_key, "not on this roster"),
        }),
      ],
    });
    await collect({ receipts: false });
    expect(await messageLog.get("conv-2")).toEqual([
      expect.objectContaining({ body: "carried on" }),
    ]);
  });

  it("reads a repeated pre-key message on the session it already opened", async () => {
    // A sender goes on marking its messages as pre-key until it hears back on
    // that session, so the second and third of them name a prekey the receiver
    // has already spent. Opening a session is the one thing that cannot answer
    // them, and reaching for it first is how a conversation used to die after
    // exactly one message each way.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, payload: from(THEIRS.identity_key, "first", "otk-1") }),
        queued({ id: 2, payload: from(THEIRS.identity_key, "second", "otk-1") }),
      ],
    });

    await collect();

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "first", mine: false }),
      expect.objectContaining({ body: "second", mine: false }),
    ]);
    expect(api.ackQueue).toHaveBeenCalledWith({ device_id: OURS.id, message_ids: [1, 2] });
  });

  it("answers on the session a pre-key message opened rather than a second one", async () => {
    // The reply looks a session up by the device it is with, and until the
    // inbound path recorded that, answering somebody this device was already
    // talking to opened a fresh session and spent another of their prekeys.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from(THEIRS.identity_key, "hello", "otk-1") })],
    });
    await collect();
    api.collectQueue.mockResolvedValue({ items: [] });

    await sendText("conv-1", [7], "hello back");

    expect(api.claimSessionKeys).not.toHaveBeenCalled();
  });

  it("tells the sender their message reached this device", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from(THEIRS.identity_key, "hello", "otk-1") })],
    });

    await collect();

    // One receipt naming what arrived, addressed to their devices and not to
    // this account's own -- a receipt for yourself tells nobody anything.
    const [, body] = api.sendMessages.mock.calls[0];
    // And it announces nothing: the far end is woken to collect it, but a bell
    // line naming a sender and counting what they said is not what this is.
    expect(body.silent).toBe(true);
    expect(
      body.messages.map((message: { recipient_device_id: string }) => message.recipient_device_id)
    ).toEqual([THEIRS.device_id]);
    const [stored] = await messageLog.get("conv-1");
    expect(JSON.parse(JSON.parse(body.messages[0].payload).body)).toEqual({
      v: 1,
      kind: "receipt",
      state: "delivered",
      ids: [stored.id],
    });
    // One collection reads the account's devices, the conversation list and
    // the sender's directory once, however many steps inside it need them.
    expect(api.listDevices).toHaveBeenCalledTimes(1);
    expect(api.listConversations).toHaveBeenCalledTimes(1);
    expect(api.readDirectory).toHaveBeenCalledTimes(1);
  });

  it("says nothing about a message when receipts are switched off", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from(THEIRS.identity_key, "hello", "otk-1") })],
    });

    await collect({ receipts: false });

    expect(api.sendMessages).not.toHaveBeenCalled();
    // The message is still collected and read: the switch is about what this
    // account reports, not about what it receives.
    expect(await messageLog.get("conv-1")).toHaveLength(1);
  });

  it("encrypts one copy per device across a whole roster", async () => {
    // Three people, one device each, plus this account's other tab. There is no
    // group key: a roster costs one copy per destination device.
    const CAROL = {
      device_id: "device-c",
      identity_key: "carol",
      fingerprint_key: "fp",
      signature: "signed:9",
    };
    api.readDirectory.mockImplementation(async (userId: number) =>
      userId === 9 ? { user_id: 9, devices: [CAROL] } : { user_id: 7, devices: [THEIRS] }
    );
    api.claimSessionKeys.mockImplementation(async (userId: number) =>
      userId === 9
        ? { user_id: 9, devices: [{ ...CAROL, one_time_key: ONE_TIME_KEY }] }
        : { user_id: 7, devices: [{ ...THEIRS, one_time_key: ONE_TIME_KEY }] }
    );

    await sendText("conv-1", [7, 9], "for both of you");

    const [, body] = api.sendMessages.mock.calls.at(-1)!;
    const addressed = body.messages.map(
      (m: { recipient_device_id: string }) => m.recipient_device_id
    );
    expect(addressed).toContain(THEIRS.device_id);
    expect(addressed).toContain(CAROL.device_id);
    expect(addressed).toContain(OUR_PHONE.id);
    // One claim each, not one per device: the endpoint answers for the whole
    // account, and asking twice would spend two of their prekeys.
    expect(api.claimSessionKeys).toHaveBeenCalledTimes(2);
  });

  it("still reaches the rest when one member has published no device", async () => {
    api.readDirectory.mockImplementation(async (userId: number) =>
      userId === 9 ? { user_id: 9, devices: [] } : { user_id: 7, devices: [THEIRS] }
    );

    await sendText("conv-1", [7, 9], "somebody is listening");

    const [, body] = api.sendMessages.mock.calls.at(-1)!;
    const addressed = body.messages.map(
      (m: { recipient_device_id: string }) => m.recipient_device_id
    );
    expect(addressed).toContain(THEIRS.device_id);
  });

  it("refuses when no member on the roster can receive it", async () => {
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [] });

    await expect(sendText("conv-1", [7, 9], "into the void")).rejects.toBeInstanceOf(
      RecipientHasNoDeviceError
    );
    expect(api.sendMessages).not.toHaveBeenCalled();
  });

  it("moves a message forward when a receipt for it arrives", async () => {
    const sent = await sendText("conv-1", [7], "hello");
    api.sendMessages.mockClear();
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "receipt", state: "read", ids: [sent.id] })
          ),
        }),
      ],
    });

    await collect();

    const [stored] = await messageLog.get("conv-1");
    expect(stored.receipt).toBe("read");
    // A receipt is news, not a message: it does not join the thread.
    expect(await messageLog.get("conv-1")).toHaveLength(1);
  });

  it("does not let a receipt fall back to an earlier state", async () => {
    // A device that was away collects a read and a delivered together, in
    // whichever order the queue holds them.
    const sent = await sendText("conv-1", [7], "hello");
    const receipt = (state: string) =>
      from(THEIRS.identity_key, JSON.stringify({ v: 1, kind: "receipt", state, ids: [sent.id] }));
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, message_type: 1, payload: receipt("read") }),
        queued({ id: 2, message_type: 1, payload: receipt("delivered") }),
      ],
    });

    await collect();

    expect((await messageLog.get("conv-1"))[0].receipt).toBe("read");
  });

  it("puts their reaction on the message it names, not in the thread", async () => {
    const sent = await sendText("conv-1", [7], "monday?");
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "reaction", targetId: sent.id, emoji: "👍", on: true })
          ),
        }),
      ],
    });

    await collect();

    const stored = await messageLog.get("conv-1");
    expect(stored).toHaveLength(1);
    expect(stored[0].reactions).toEqual({ "👍": { mine: false, theirs: true } });
  });

  it("refuses an edit of a message the sender did not write", async () => {
    // The side an envelope arrived on is the whole of the authorization: this
    // one came over their session and names one of ours.
    const sent = await sendText("conv-1", [7], "mine to say");
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({
              v: 1,
              kind: "edit",
              targetId: sent.id,
              at: "2026-09-02T00:00:00Z",
              body: "put in their mouth",
            })
          ),
        }),
      ],
    });

    await collect();

    expect((await messageLog.get("conv-1"))[0].body).toBe("mine to say");
  });

  it("takes their message off this device when they take it back", async () => {
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "never mind") })],
    });
    await collect();
    const [theirs] = await messageLog.get("conv-1");

    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 2,
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "remove", targetId: theirs.id })
          ),
        }),
      ],
    });
    await collect();

    // A line saying one was here, rather than a gap where one was.
    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ id: theirs.id, body: "", removedAt: expect.any(String) }),
    ]);
  });

  it("writes nothing down about an action it could not send", async () => {
    // The other order reads better and is how the two sides come to disagree
    // for good: nothing here retries, so an action written down locally after
    // a failed send is one this device believes and theirs never hears about.
    const sent = await sendText("conv-1", [7], "monday?");
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [] });

    await expect(sendRemove("conv-1", [7], sent.id)).rejects.toThrow();

    expect((await messageLog.get("conv-1"))[0].removedAt).toBeUndefined();
  });

  it("refuses to act on a message that is not there to act on", async () => {
    // Nothing sent either: an envelope about a message this device does not
    // hold is one the other side would apply to something it does.
    api.sendMessages.mockClear();

    expect(await sendReaction("conv-1", [7], "never-existed", "👍", true)).toBe(false);
    expect(await sendEdit("conv-1", [7], "never-existed", "words")).toBe(false);
    expect(api.sendMessages).not.toHaveBeenCalled();
  });

  it("says nothing to their bell about a reaction, an edit or a removal", async () => {
    // None of the three is somebody saying something, so none of them should
    // arrive as a notification -- only as something to collect.
    const sent = await sendText("conv-1", [7], "monday?");
    api.sendMessages.mockClear();

    await sendReaction("conv-1", [7], sent.id, "👍", true);
    await sendEdit("conv-1", [7], sent.id, "monday?!");
    await sendRemove("conv-1", [7], sent.id);

    expect(api.sendMessages).toHaveBeenCalledTimes(3);
    for (const [, body] of api.sendMessages.mock.calls) {
      expect(body.silent).toBe(true);
    }
  });

  it("keeps a reply that answers a message this device never had", async () => {
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: from(
            "theirs",
            JSON.stringify({
              v: 1,
              kind: "text",
              id: "x",
              at: "2026-09-01T00:00:00Z",
              body: "yes",
              replyTo: "one-this-device-never-saw",
            })
          ),
        }),
      ],
    });

    await collect();

    // The quote is what goes missing, never the words.
    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ body: "yes", replyTo: "one-this-device-never-saw" }),
    ]);
  });

  it("reports only what this look actually read", async () => {
    // markRead runs on every change to the thread's length. Reporting the whole
    // thread each time would say "read" again for messages answered an hour ago
    // -- once per keystroke that lengthened it.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({ id: 1, payload: from(THEIRS.identity_key, "first", "otk-1") }),
        queued({ id: 2, payload: from(THEIRS.identity_key, "second", "otk-1") }),
      ],
    });
    await collect({ receipts: false });
    const log = await messageLog.get("conv-1");

    await markRead("conv-1", { memberIds: [7] });
    const first = JSON.parse(
      JSON.parse(api.sendMessages.mock.calls[0][1].messages[0].payload).body
    );
    expect(first).toEqual({
      v: 1,
      kind: "receipt",
      state: "read",
      ids: [log[0].id, log[1].id],
    });

    api.sendMessages.mockClear();
    await markRead("conv-1", { memberIds: [7] });
    expect(api.sendMessages).not.toHaveBeenCalled();
  });

  it("reads a half-written envelope as the words it may always have been", async () => {
    // An envelope missing the id it promised would be filed under `undefined`,
    // where the next one like it looks like the same message and is dropped as
    // a duplicate -- acknowledged away, off the server, never in the log.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 1,
          payload: from(THEIRS.identity_key, JSON.stringify({ v: 1, kind: "text" }), "otk-1"),
        }),
        queued({
          id: 2,
          payload: from(THEIRS.identity_key, JSON.stringify({ v: 1, kind: "text" })),
        }),
      ],
    });

    await collect({ receipts: false });

    // Two messages, two entries: the queue row's id is unique per item.
    expect(await messageLog.get("conv-1")).toHaveLength(2);
  });

  it("ignores a receipt that does not say what it is about", async () => {
    const sent = await sendText("conv-1", [7], "hello");
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          message_type: 1,
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "receipt", state: "read" })
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    // Not a receipt it can act on, so the message keeps the state it had.
    const stored = (await messageLog.get("conv-1")).find((m) => m.id === sent.id);
    expect(stored?.receipt).toBeUndefined();
  });

  it("runs one collection at a time across tabs, with one more waiting behind it", async () => {
    // Web Locks as the browser grants them: one holder per name, the rest in
    // order, and `ifAvailable` refused while anybody holds or waits.
    const holders = new Map<string, number>();
    const tails = new Map<string, Promise<unknown>>();
    const request = (name: string, ...rest: unknown[]) => {
      const callback = rest.at(-1) as (lock: object | null) => unknown;
      const ifAvailable = rest.length === 2 && (rest[0] as LockOptions).ifAvailable;
      if (ifAvailable && (holders.get(name) ?? 0) > 0) return Promise.resolve(callback(null));
      holders.set(name, (holders.get(name) ?? 0) + 1);
      const run = (tails.get(name) ?? Promise.resolve())
        .then(() => callback({ name }))
        .finally(() => holders.set(name, (holders.get(name) ?? 1) - 1));
      tails.set(
        name,
        run.catch(() => undefined)
      );
      return run;
    };
    Object.defineProperty(navigator, "locks", { value: { request }, configurable: true });
    let running = 0;
    let most = 0;
    api.collectQueue.mockImplementation(async () => {
      running += 1;
      most = Math.max(most, running);
      await new Promise((resolve) => setTimeout(resolve, 5));
      running -= 1;
      return { items: [] };
    });

    try {
      const first = collect();
      await vi.waitFor(() => expect(api.collectQueue).toHaveBeenCalledTimes(1));
      // Two more while it runs: the second reads the queue after the first, so
      // nothing that arrived meanwhile waits for another prompt, and the third
      // has nothing to add.
      const [, , third] = await Promise.all([first, collect(), collect()]);
      expect(api.collectQueue).toHaveBeenCalledTimes(2);
      expect(most).toBe(1);
      expect(third).toEqual([]);
    } finally {
      Reflect.deleteProperty(navigator, "locks");
    }
  });

  it("takes a message nothing here will ever read off the server", async () => {
    // From a device no directory lists, every directory having been read: left
    // there, it would sit in front of everything after it for good.
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("a-device-nobody-knows", "unreadable") })],
    });

    await collect();

    expect(api.ackQueue).toHaveBeenCalledWith({ device_id: OURS.id, message_ids: [1] });
    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("leaves a message on the server when its sender could not be looked up", async () => {
    api.readDirectory.mockRejectedValue(new Error("offline"));
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "try me later") })],
    });

    await collect();

    expect(api.ackQueue).not.toHaveBeenCalled();
  });

  it("leaves a message on the server when the ratchet could not be reached", async () => {
    // A refusal is the ratchet's answer about the message. A call that fails is
    // nothing of the kind, and never a reason to throw the message away.
    vi.spyOn(ratchet, "createInboundSession").mockRejectedValueOnce(new Error("worker gone"));
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "try me later") })],
    });

    await collect();

    expect(api.ackQueue).not.toHaveBeenCalled();
  });

  it("reads past a page of messages it has to leave", async () => {
    api.collectQueue
      .mockResolvedValueOnce({
        items: [queued({ id: 1, payload: from("theirs", "one") })],
        more: true,
      })
      .mockResolvedValueOnce({
        items: [queued({ id: 2, message_type: 1, payload: from("theirs", "two") })],
      });

    await collect({ receipts: false });

    expect(api.collectQueue).toHaveBeenLastCalledWith({ device_id: OURS.id, after: 1 });
    expect((await messageLog.get("conv-1")).map((m) => m.body)).toEqual(["one", "two"]);
  });
});

describe("history between this account's own devices", () => {
  /** What a device of this account's says, over a session marked as its own. */
  const fromOwnDevice = (envelope: Record<string, unknown>, prekey?: string) =>
    from(OUR_PHONE.identity_key, JSON.stringify(envelope), prekey);

  const sentEnvelopes = () =>
    api.sendMessages.mock.calls.flatMap(([, body]) =>
      body.messages.map(
        (message) => JSON.parse(JSON.parse(message.payload).body) as Record<string, unknown>
      )
    );

  it("asks the account's other devices once, and not again", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");

    await collect({ receipts: false });
    await collect({ receipts: false });

    const asks = sentEnvelopes().filter((envelope) => envelope.kind === "history-request");
    expect(asks).toHaveLength(1);
    expect(asks[0]).toMatchObject({ deviceId: OURS.id, fingerprint: "fp" });
  });

  it("asks inside a conversation this account has accepted", async () => {
    // The newest conversation can be an invitation nobody has answered, and the
    // server takes nothing sent into one of those.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    api.listConversations.mockResolvedValue({
      conversations: [
        {
          id: "invited",
          other_user_id: 8,
          member_ids: [8],
          created_at: "2026-09-02T00:00:00Z",
          pending: true,
        },
        { id: "conv-1", other_user_id: 7, member_ids: [7], created_at: "2026-09-01T00:00:00Z" },
      ],
    });

    await collect({ receipts: false });

    const asked = api.sendMessages.mock.calls.find(([, body]) =>
      body.messages.some(
        (message) => JSON.parse(JSON.parse(message.payload).body).kind === "history-request"
      )
    );
    expect(asked?.[0]).toBe("conv-1");
  });

  it("asks loudly enough to reach a device nobody is looking at", async () => {
    // The far device has to be picked up by a person before it can answer, and
    // a frame on a socket that is not open will not do that. This is the only
    // own-device envelope worth waking a phone for — it says "worth waking" and
    // never what for, since the server cannot read it either way.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");

    await collect({ receipts: false });

    const asked = api.sendMessages.mock.calls.find(([, body]) =>
      body.messages.some(
        (message) => JSON.parse(JSON.parse(message.payload).body).kind === "history-request"
      )
    );
    expect(asked?.[1]).toMatchObject({ silent: true, wake_own_devices: true });
  });

  it("wakes the account's devices once, however many it asks", async () => {
    // The push reaches every other device the account has, so one per device
    // asked rang each phone once per device on the account.
    const tablet = { id: "device-3", identity_key: "tablet", created_at: "2026-08-15T00:00:00Z" };
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    api.listDevices.mockResolvedValue({
      devices: [ownDevice(OURS), ownDevice(OUR_PHONE), ownDevice(tablet)],
    });
    api.claimOwnSessionKeys.mockResolvedValue({
      user_id: 1,
      devices: [keyFor(OUR_PHONE), keyFor(tablet)],
    });

    await collect({ receipts: false });

    const asks = api.sendMessages.mock.calls.filter(([, body]) =>
      body.messages.some(
        (message) => JSON.parse(JSON.parse(message.payload).body).kind === "history-request"
      )
    );
    expect(asks).toHaveLength(2);
    expect(asks.filter(([, body]) => body.wake_own_devices)).toHaveLength(1);
  });

  it("does not wake anything for an ordinary own-device envelope", async () => {
    // A client reporting that it collected something is a client talking to
    // itself. Waking a phone for it would train somebody to ignore the one that
    // matters.
    await collect({ receipts: true });

    const woken = api.sendMessages.mock.calls.filter(([, body]) => body.wake_own_devices);
    expect(woken).toEqual([]);
  });

  it("does not ask when this device already has the messages", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await messageLog.append("conv-1", {
      id: "m1",
      at: "2026-09-01T00:00:00Z",
      body: "already here",
      mine: false,
    });

    await collect({ receipts: false });

    // Every device of the account runs this. One that asks for what it is
    // sitting on leaves two screens each asking the other, each showing a
    // different code, and nothing to compare either against.
    expect(sentEnvelopes().filter((e) => e.kind === "history-request")).toEqual([]);
    // And settled, rather than reconsidered on every collection.
    expect(await historyAsk.get()).toBe("closed");
  });

  it("says it is waiting while its ask is unanswered", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");

    await collect({ receipts: false });

    // And when it will stop saying so, which is what takes the notice down on
    // a tab nobody touches in the meantime.
    expect((await historyAskWaiting())?.expiresAt).toBeGreaterThan(Date.now());
  });

  it("asks again after a first attempt that never got out", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    // The other device has no prekey to open a session with, so the first
    // request cannot be sent -- and a message from the other party lands in the
    // same collection, which is what used to be taken as proof this device had
    // its history all along.
    api.claimOwnSessionKeys.mockResolvedValueOnce({ user_id: 1, devices: [] });
    api.collectQueue.mockResolvedValueOnce({
      items: [queued({ payload: from("theirs", "arrived in between") })],
    });

    await collect({ receipts: false });
    expect(sentEnvelopes().filter((e) => e.kind === "history-request")).toEqual([]);
    expect(await messageLog.get("conv-1")).toHaveLength(1);

    await collect({ receipts: false });

    // What a device arrived with is what decides this, and that does not change
    // because something arrived afterwards.
    expect(sentEnvelopes().filter((e) => e.kind === "history-request")).toHaveLength(1);
  });

  it("does not ask when it is the only device on the account", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS)] });

    await collect({ receipts: false });

    expect(sentEnvelopes().filter((e) => e.kind === "history-request")).toEqual([]);
  });

  it("does not ask a device that registered after it", async () => {
    // The reported bug, from the older browser's side. Sign into one browser,
    // send and receive for a while, then sign into a second: the first was
    // marked eligible when it registered with an empty log and stayed that way
    // the whole time it was alone, so the moment the second appeared both were
    // eligible and each asked the other for history the other did not have.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OUR_PHONE.id);
    await accountPickle.set("account");
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OUR_PHONE), ownDevice(OURS)] });
    // A key for the device it would wrongly ask, so nothing but the direction
    // rule can be what stops the send.
    api.claimOwnSessionKeys.mockResolvedValue({ user_id: 1, devices: [keyFor(OURS)] });

    await collect({ receipts: false });

    // OUR_PHONE came first. Nothing registered later can be holding what it is
    // missing, so there is no direction for a request to travel in.
    expect(sentEnvelopes().filter((e) => e.kind === "history-request")).toEqual([]);
  });

  it("settles the question for the oldest device instead of leaving it armed", async () => {
    // What made the bug wait: being alone was treated as a failed attempt, so
    // eligibility was kept and fired at whichever device arrived next. The
    // account's first device is the source of its history, which is an answer,
    // not a postponement.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OUR_PHONE.id);
    await accountPickle.set("account");
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OUR_PHONE)] });

    await collect({ receipts: false });

    expect(await historyAsk.get()).toBe("closed");
  });

  it("asks one way round when two devices register in the same instant", async () => {
    // Registration time is what decides direction, and it can tie. Without a
    // tie-break both devices read themselves as the junior one and the original
    // bug comes back for exactly the pair most likely to hit it -- two browsers
    // signed into at once.
    const sameMoment = "2026-09-01T00:00:00Z";
    // The id settles it, and "device-1" sorts first — so OURS is the elder of
    // the pair and the ask has to travel from the phone to it.
    const elder = { ...OURS, created_at: sameMoment };
    const junior = { ...OUR_PHONE, created_at: sameMoment };
    api.listDevices.mockResolvedValue({ devices: [ownDevice(elder), ownDevice(junior)] });
    // Both reachable: an ask could get out whichever way it tried to go, so the
    // ordering is the only thing deciding which one actually does.
    api.claimOwnSessionKeys.mockResolvedValue({
      user_id: 1,
      devices: [keyFor(elder), keyFor(junior)],
    });

    await forgetDevice();

    await deviceOwner.set(1);
    await deviceId.set(elder.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    const fromElder = sentEnvelopes().filter((e) => e.kind === "history-request");

    await forgetDevice();

    await deviceOwner.set(1);
    await deviceId.set(junior.id);
    await accountPickle.set("account");
    api.sendMessages.mockClear();
    await collect({ receipts: false });
    const fromJunior = sentEnvelopes().filter((e) => e.kind === "history-request");

    expect(fromElder).toEqual([]);
    expect(fromJunior).toHaveLength(1);
    // And it is addressed to the elder, not bounced back at itself.
    expect(fromJunior[0]).toMatchObject({ deviceId: junior.id });
  });

  it("stops saying it is waiting once the notice has had its day", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    expect(await historyAskWaiting()).toBeDefined();

    const aDayLater = Date.now() + HISTORY_ASK_NOTICE_MS + 1;
    const clock = vi.spyOn(Date, "now").mockReturnValue(aDayLater);

    // The notice gives up; the question does not. Nothing expires a queued
    // request, so an answer that arrives next week still has an open ask to
    // land in -- what stops is telling somebody to go and do a thing they have
    // had a day to do.
    expect(await historyAskWaiting()).toBeUndefined();
    expect(await historyAsk.get()).toMatchObject({ asked: [OUR_PHONE.id] });
    clock.mockRestore();
  });

  it("stops saying it is waiting once somebody puts the notice away", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    expect(await historyAskWaiting()).toBeDefined();

    await historyAsk.dismissNotice();

    // The same split as the day running out: the notice goes, the question
    // stays. Dismissing is somebody saying they have read it, not somebody
    // calling the transfer off.
    expect(await historyAskWaiting()).toBeUndefined();
    expect(await historyAsk.get()).toMatchObject({ asked: [OUR_PHONE.id] });
  });

  it("still lands the history approved after the notice was put away", async () => {
    // The thing a dismissal must not do. Closing the ask here would mean
    // somebody who hid the banner, walked to their laptop and approved it would
    // have their history arrive and be thrown away.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    const asked = sentEnvelopes().find((envelope) => envelope.kind === "history-request");

    await historyAsk.dismissNotice();

    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: fromOwnDevice(
            {
              v: 1,
              kind: "history",
              requestId: asked?.requestId,
              conversationId: "conv-1",
              seq: 1,
              last: true,
              messages: [
                { id: "m0", body: "from before this device", at: "2026-08-30", mine: false },
              ],
            },
            "otk-1"
          ),
        }),
      ],
    });
    await collect({ receipts: false });

    expect((await messageLog.get("conv-1")).map((entry) => entry.id)).toEqual(["m0"]);
    // And settled by the answer, the way it would have been without the
    // dismissal.
    expect(await historyAsk.get()).toBe("closed");
  });

  it("does not put a settled ask back by dismissing it", async () => {
    // Two tabs: one answers while the other still has the banner up. A plain
    // write would resurrect an ask that has just been closed.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    await historyAsk.close();

    await historyAsk.dismissNotice();

    expect(await historyAsk.get()).toBe("closed");
  });

  it("still takes the history a late answer brings", async () => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    const asked = sentEnvelopes().find((envelope) => envelope.kind === "history-request");
    const clock = vi.spyOn(Date, "now").mockReturnValue(Date.now() + HISTORY_ASK_NOTICE_MS * 7);
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: fromOwnDevice(
            {
              v: 1,
              kind: "history",
              requestId: asked?.requestId,
              seq: 1,
              last: true,
              conversationId: "conv-1",
              messages: [
                { id: "m0", body: "from before this device", at: "2026-08-30", mine: false },
              ],
            },
            "otk-1"
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    expect(await messageLog.get("conv-1")).toEqual([
      expect.objectContaining({ id: "m0", body: "from before this device" }),
    ]);
    clock.mockRestore();
  });

  /** A history request from the phone, as its first message to this device. */
  const phoneAsks = (fingerprint = "fp") =>
    queued({
      payload: fromOwnDevice(
        { v: 1, kind: "history-request", requestId: "r1", deviceId: OUR_PHONE.id, fingerprint },
        "otk-1"
      ),
    });

  /** This browser's baseline is the account as it was; then the phone signs in and asks. */
  const phoneSignsIn = async () => {
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS)] });
    await collect({ receipts: false });
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS), ownDevice(OUR_PHONE)] });
    api.collectQueue.mockResolvedValue({ items: [phoneAsks()] });
    await collect({ receipts: false });
    return (await ownDeviceWaiting())!;
  };

  it("holds a new device until it is confirmed, then sends the history it asked for", async () => {
    await messageLog.append("conv-1", { id: "m1", body: "one", at: "2026-09-01", mine: true });
    await messageLog.append("conv-1", { id: "m2", body: "two", at: "2026-09-02", mine: false });
    const waiting = await phoneSignsIn();

    // Held: what it sent waits on the server, nothing from here reaches it, and
    // the prompt about it has the history it asked for already ticked.
    expect(api.ackQueue).not.toHaveBeenCalled();
    expect(waiting).toMatchObject({ deviceId: OUR_PHONE.id, asked: true, label: null });
    api.collectQueue.mockResolvedValue({ items: [] });
    await sendText("conv-1", [7], "not for the phone yet");
    const [, body] = api.sendMessages.mock.calls.at(-1)!;
    expect(body.messages.map((m) => m.recipient_device_id)).toEqual([THEIRS.device_id]);

    await answerNewDevice(waiting, { mine: true, sendHistory: true });
    api.collectQueue.mockResolvedValue({ items: [phoneAsks()] });
    await collect({ receipts: false });

    const chunks = sentEnvelopes().filter((envelope) => envelope.kind === "history");
    expect(chunks.at(-1)).toMatchObject({ last: true });
    expect(
      chunks.flatMap((chunk) => (chunk.messages as { id: string }[]).map((m) => m.id))
    ).toEqual(expect.arrayContaining(["m1", "m2"]));
    expect(await ownDeviceWaiting()).toBeNull();
  });

  it("sends a long thread in parts the server takes", async () => {
    const long = "x".repeat(4000);
    for (let index = 0; index < 40; index += 1) {
      await messageLog.append("conv-1", {
        id: `m${index}`,
        body: long,
        at: `2026-09-01T00:00:${String(index).padStart(2, "0")}Z`,
        mine: true,
      });
    }
    await answerNewDevice(await phoneSignsIn(), { mine: true, sendHistory: true });
    api.collectQueue.mockResolvedValue({ items: [phoneAsks()] });
    await collect({ receipts: false });

    const parts = api.sendMessages.mock.calls
      .flatMap(([, body]) => body.messages.map((m) => JSON.parse(m.payload).body as string))
      .filter((text) => JSON.parse(text).kind === "history");
    // Forty of these is 160 KB: one part of forty would be refused every time.
    expect(parts.length).toBeGreaterThan(2);
    for (const text of parts) {
      expect(new TextEncoder().encode(text).length).toBeLessThanOrEqual(64 * 1024);
    }
    const sent = parts.flatMap((text) =>
      (JSON.parse(text).messages as { id: string }[]).map((m) => m.id)
    );
    expect(sent).toEqual(expect.arrayContaining(Array.from({ length: 40 }, (_, i) => `m${i}`)));
  });

  it("declines for a device confirmed without its history, and removes one that is not the account's", async () => {
    await answerNewDevice(await phoneSignsIn(), { mine: true, sendHistory: false });
    await collect({ receipts: false });

    // Said out loud, so the far device stops waiting.
    expect(sentEnvelopes().filter((e) => e.kind === "history-declined")).toHaveLength(1);
    expect(sentEnvelopes().filter((e) => e.kind === "history")).toEqual([]);

    const TABLET = { id: "device-3", identity_key: "tablet" };
    api.listDevices.mockResolvedValue({
      devices: [ownDevice(OURS), ownDevice(OUR_PHONE), ownDevice(TABLET)],
    });
    api.collectQueue.mockResolvedValue({ items: [] });
    await collect({ receipts: false });
    const tablet = (await ownDeviceWaiting())!;
    // Still asked about until the server has taken it off the account.
    api.removeDevice.mockRejectedValueOnce(new Error("offline"));
    await expect(answerNewDevice(tablet, { mine: false, sendHistory: false })).rejects.toThrow();
    expect(await ownDeviceWaiting()).toMatchObject({ deviceId: TABLET.id });
    api.removeDevice.mockResolvedValueOnce(undefined);
    await answerNewDevice(tablet, { mine: false, sendHistory: false });
    expect(api.removeDevice).toHaveBeenLastCalledWith(TABLET.id);
    expect(await ownDeviceWaiting()).toBeNull();
  });

  it("releases a new device only once four matching pictures are confirmed on both", async () => {
    const waiting = await phoneSignsIn();
    await historyAsk.open("request-1", [OUR_PHONE.id]);
    const sent: { to_device_id: string; body: string }[] = [];
    api.sendVerification.mockImplementation(async (body) => {
      sent.push(body);
    });
    const textOf = (body: string) => JSON.parse(body).message as string;
    const last = () => JSON.parse(textOf(sent.at(-1)!.body));
    const fromPhone = (message: Record<string, unknown>, signedBy = OUR_PHONE.id) => {
      const text = JSON.stringify(message);
      api.collectVerification.mockResolvedValueOnce({
        items: [
          {
            id: 1,
            sender_device_id: OUR_PHONE.id,
            body: JSON.stringify({
              message: text,
              signature: `signed:${signedBy}|${OURS.id}|${text}`,
            }),
          },
        ],
      });
    };
    const sha256 = async (text: string) =>
      btoa(
        String.fromCharCode(
          ...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)))
        )
      );

    // The phone's key does not match what it committed to: nothing is shown,
    // the phone is told, and it stays held.
    await startVerification(waiting, { sendHistory: false });
    const bad = last();
    await engine.verificationOpen("phone-bad");
    fromPhone({ v: 1, txn: bad.txn, type: "accept", commitment: "not-it" });
    await collectVerification();
    fromPhone({ v: 1, txn: bad.txn, type: "key", key: await engine.verificationOpen("other") });
    await collectVerification();
    expect(verificationView()).toMatchObject({ phase: "failed", reason: "mismatch" });
    expect(last()).toMatchObject({ type: "cancel", txn: bad.txn });
    expect(await ownDeviceWaiting()).toMatchObject({ deviceId: OUR_PHONE.id });

    await startVerification(waiting, { sendHistory: false });
    const start = sent.at(-1)!;
    const { txn } = last();
    expect(txn).not.toBe(bad.txn);
    expect(start.to_device_id).toBe(OUR_PHONE.id);
    expect(JSON.parse(start.body).signature).toBe(
      `signed:${OURS.id}|${OUR_PHONE.id}|${textOf(start.body)}`
    );
    const phoneKey = await engine.verificationOpen("phone");
    const accept = {
      v: 1,
      txn,
      type: "accept",
      commitment: await sha256(phoneKey + textOf(start.body)),
    };
    // Signed by some other device, it is passed over as if never sent.
    const before = sent.length;
    fromPhone(accept, "device-3");
    await collectVerification();
    expect(sent).toHaveLength(before);
    fromPhone(accept);
    await collectVerification();
    const ourKey = last().key as string;
    engine.verificationEstablish("phone", ourKey);
    fromPhone({ v: 1, txn, type: "key", key: phoneKey });
    await collectVerification();

    const shown = verificationView();
    if (shown.phase !== "compare") throw new Error(`expected pictures, got ${shown.phase}`);
    const phoneSees = engine.verificationEmoji(
      "phone",
      [
        "INITIATIVE_DEVICE_VERIFICATION_V1_EMOJI",
        1,
        OURS.id,
        ourKey,
        OUR_PHONE.id,
        phoneKey,
        txn,
      ].join("|")
    );
    expect(shown.emoji).toHaveLength(4);
    expect(phoneSees).toHaveLength(4);
    expect(shown.emoji.map((entry) => entry.name)).toEqual(
      phoneSees.map((index) => emojiAt(index).name)
    );

    // Its word alone releases nothing: the person here has not said yet.
    const macInfo = (a: string, b: string) =>
      ["INITIATIVE_DEVICE_VERIFICATION_V1_MAC", 1, a, b, txn].join("|");
    fromPhone({
      v: 1,
      txn,
      type: "mac",
      mac: engine.verificationMac("phone", "fp|phone", macInfo(OUR_PHONE.id, OURS.id)),
    });
    await collectVerification();
    expect(await ownDeviceWaiting()).toMatchObject({ deviceId: OUR_PHONE.id });

    await confirmMatch();
    expect(
      engine.verificationCheckMac("phone", "fp|mine", macInfo(OURS.id, OUR_PHONE.id), last().mac)
    ).toBe(true);
    expect(verificationView()).toMatchObject({ phase: "verified" });
    expect(await ownDeviceWaiting()).toBeNull();
    // Verified, so nothing is left to tell anybody to go and verify; the
    // history asked for can still be on its way.
    expect(await historyAskWaiting()).toBeUndefined();
    expect(await historyAsk.get()).toMatchObject({ requestId: "request-1" });
  });

  it("asks about a device already trusted before it sends that device history", async () => {
    await messageLog.append("conv-1", { id: "m1", body: "one", at: "2026-09-01", mine: true });
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS), ownDevice(OUR_PHONE)] });
    api.collectQueue.mockResolvedValue({ items: [phoneAsks()] });
    await collect({ receipts: false });
    api.collectQueue.mockResolvedValue({ items: [] });
    await collect({ receipts: false });

    // The same question a new device gets, with the request still waiting.
    expect(sentEnvelopes().filter((e) => e.kind === "history-declined")).toEqual([]);
    const waiting = (await ownDeviceWaiting())!;
    expect(waiting).toMatchObject({ deviceId: OUR_PHONE.id, asked: true });

    await answerNewDevice(waiting, { mine: true, sendHistory: true });
    await collect({ receipts: false });
    expect(
      sentEnvelopes()
        .filter((e) => e.kind === "history")
        .at(-1)
    ).toMatchObject({
      last: true,
    });
  });

  it("answers no request from a device the directory does not know", async () => {
    // The fingerprint in the request is a convenience for whoever compares two
    // screens. What decides is the directory's own entry for that device.
    api.collectQueue.mockResolvedValue({ items: [phoneAsks("a-different-key")] });

    await collect({ receipts: false });

    expect(sentEnvelopes().filter((e) => String(e.kind).startsWith("history"))).toEqual([]);
  });

  it("reads a request only on a session with one of its own devices", async () => {
    // These travel between an account's own devices, on a session this device
    // opened with another of its own. The other party's session is not one.
    await approvedDevices.decide(OUR_PHONE.id, "fp", true);
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({
              v: 1,
              kind: "history-request",
              requestId: "r1",
              deviceId: OUR_PHONE.id,
              fingerprint: "fp",
            }),
            "otk-1"
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    expect(sentEnvelopes().filter((e) => String(e.kind).startsWith("history"))).toEqual([]);
  });

  /**
   * Ask for this device's history, and answer with the id it asked under.
   *
   * Anything seeded lands after the ask, because only a device holding nothing
   * asks -- a message that arrives while the question is outstanding is what
   * puts something in the log of a device waiting on an answer.
   */
  const askThenAnswer = async (chunk: Record<string, unknown>, seed?: () => Promise<void>) => {
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });
    await seed?.();
    const asked = sentEnvelopes().find((envelope) => envelope.kind === "history-request");
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: fromOwnDevice(
            { v: 1, kind: "history", requestId: asked?.requestId, seq: 1, last: true, ...chunk },
            "otk-1"
          ),
        }),
      ],
    });
    await collect({ receipts: false });
  };

  it("fills in what it is missing and leaves what it holds alone", async () => {
    await askThenAnswer(
      {
        conversationId: "conv-1",
        messages: [
          { id: "m1", body: "a different account of it", at: "2026-09-01", mine: true },
          { id: "m0", body: "from before this device", at: "2026-08-30", mine: false },
        ],
      },
      () =>
        messageLog.append("conv-1", {
          id: "m1",
          body: "already here",
          at: "2026-09-01",
          mine: true,
        })
    );

    const thread = await messageLog.get("conv-1");
    // In the order they were written, not the order they arrived in.
    expect(thread.map((entry) => entry.id)).toEqual(["m0", "m1"]);
    // This device has held m1 since it arrived, so it has had everything that
    // happened to it since. A second copy has nothing to add.
    expect(thread[1].body).toBe("already here");
  });

  it("takes history only as an answer to what it asked", async () => {
    // An answer names the question. One that names nothing this device asked is
    // not an answer to it.
    await forgetDevice();
    await deviceOwner.set(1);
    await deviceId.set(OURS.id);
    await accountPickle.set("account");
    await collect({ receipts: false });

    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: fromOwnDevice(
            {
              v: 1,
              kind: "history",
              requestId: "a-request-this-device-never-made",
              seq: 1,
              last: true,
              conversationId: "conv-1",
              messages: [{ id: "m9", body: "unasked for", at: "2026-08-30", mine: false }],
            },
            "otk-1"
          ),
        }),
      ],
    });
    await collect({ receipts: false });
    expect(await messageLog.get("conv-1")).toEqual([]);

    // Nor from a device of the account's that it did not ask.
    const asked = sentEnvelopes().find((envelope) => envelope.kind === "history-request");
    const TABLET = { id: "device-3", identity_key: "tablet", created_at: "2026-09-02T00:00:00Z" };
    api.listDevices.mockResolvedValue({
      devices: [ownDevice(OURS), ownDevice(OUR_PHONE), ownDevice(TABLET)],
    });
    await collect({ receipts: false });
    await answerNewDevice((await ownDeviceWaiting())!, { mine: true, sendHistory: false });
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          id: 2,
          payload: from(
            TABLET.identity_key,
            JSON.stringify({
              v: 1,
              kind: "history",
              requestId: asked?.requestId,
              seq: 1,
              last: true,
              conversationId: "conv-1",
              messages: [{ id: "m9", body: "not asked of it", at: "2026-08-30", mine: false }],
            }),
            "otk-2"
          ),
        }),
      ],
    });
    await collect({ receipts: false });
    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("takes nothing more once its question has been answered", async () => {
    await askThenAnswer({ conversationId: "conv-1", messages: [] });
    const asked = sentEnvelopes().find((envelope) => envelope.kind === "history-request");

    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: fromOwnDevice(
            {
              v: 1,
              kind: "history",
              requestId: asked?.requestId,
              seq: 2,
              last: true,
              conversationId: "conv-1",
              messages: [{ id: "late", body: "after the last one", at: "2026-08-30", mine: false }],
            },
            "otk-1"
          ),
        }),
      ],
    });
    await collect({ receipts: false });

    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("drops an entry that is not a message, and keeps the rest", async () => {
    await askThenAnswer({
      conversationId: "conv-1",
      messages: [
        null,
        { id: "good", body: "readable", at: "2026-08-30", mine: false },
        { body: "no id", at: "2026-08-31", mine: false },
      ],
    });

    expect((await messageLog.get("conv-1")).map((entry) => entry.id)).toEqual(["good"]);
    // Taken off the server rather than retried on every collection.
    expect(api.ackQueue).toHaveBeenCalled();
  });

  it("sends the thread of a conversation the server no longer lists", async () => {
    // Leaving a conversation takes it off that list. Its messages are still
    // here, and they are as much this device's history as any other.
    await messageLog.append("gone", { id: "m1", body: "still ours", at: "2026-09-01", mine: true });
    await approvedDevices.decide(OUR_PHONE.id, "fp", true);
    api.collectQueue.mockResolvedValue({ items: [phoneAsks()] });

    await collect({ receipts: false });

    const carried = sentEnvelopes().filter((envelope) => envelope.kind === "history");
    expect(carried.map((chunk) => chunk.conversationId)).toContain("gone");
  });

  it("reads history only on a session with one of its own devices", async () => {
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({
              v: 1,
              kind: "history",
              requestId: "r1",
              seq: 1,
              last: true,
              conversationId: "conv-1",
              messages: [{ id: "planted", body: "not from you", at: "2026-08-30", mine: true }],
            }),
            "otk-1"
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("ignores an envelope of a kind this version does not know", async () => {
    // A later version's protocol, not a message. Rendering it would print the
    // protocol into somebody's thread.
    api.collectQueue.mockResolvedValue({
      items: [
        queued({
          payload: from(
            THEIRS.identity_key,
            JSON.stringify({ v: 1, kind: "something-later", data: "x" }),
            "otk-1"
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    expect(await messageLog.get("conv-1")).toEqual([]);
    // Taken off the server rather than retried forever.
    expect(api.ackQueue).toHaveBeenCalled();
  });
});

describe("catching up on a group joined late", () => {
  /** A second member, so it can be told which of them was asked. */
  const SAM = {
    device_id: "device-8",
    identity_key: "sam",
    fingerprint_key: "fp",
    signature: "signed:9",
  };

  const asGroup = () => {
    api.listConversations.mockResolvedValue({
      conversations: [
        {
          id: "conv-1",
          other_user_id: 7,
          created_at: "2026-09-01T00:00:00Z",
          kind: "group",
          member_ids: [7, 9],
        },
      ],
    });
    api.readDirectory.mockImplementation(async (userId: number) =>
      userId === 9 ? { user_id: 9, devices: [SAM] } : { user_id: 7, devices: [THEIRS] }
    );
    api.claimSessionKeys.mockImplementation(async (userId: number) => {
      const device = userId === 9 ? SAM : THEIRS;
      return {
        user_id: userId,
        devices: [
          {
            ...device,
            one_time_key: { key_id: `k${userId}`, public_key: `pk${userId}`, signature: "otk" },
          },
        ],
      };
    });
  };

  /** Every envelope handed to the server, with the device it was addressed to. */
  const sent = () =>
    api.sendMessages.mock.calls.flatMap(([, body]) =>
      body.messages.map((message) => ({
        to: message.recipient_device_id,
        envelope: JSON.parse(JSON.parse(message.payload).body) as Record<string, unknown>,
      }))
    );

  const asks = () => sent().filter((row) => row.envelope.kind === "thread-history-request");

  it("asks every member at once, and closes on each one's last part or the wait", async () => {
    asGroup();
    await wantThreadHistory("conv-1");

    await collect({ receipts: false });
    // Everybody at once: each sends only what they said, so nothing overlaps.
    expect(asks().map((row) => row.to)).toEqual([THEIRS.device_id, SAM.device_id]);

    // Straight away again, and nobody is asked twice.
    await collect({ receipts: false });
    expect(asks()).toHaveLength(2);

    // Once the wait is up, whoever has not answered is closed too.
    const state = await threadCatchUp.get("conv-1");
    await threadCatchUp.set("conv-1", { ...state!, at: "2026-09-01T00:00:00Z" });
    await collect({ receipts: false });
    expect(await threadCatchUp.get("conv-1")).toBeUndefined();
    expect(asks()).toHaveLength(2);
  });

  it("files each member's messages as theirs, and closes the ask with the last of them", async () => {
    asGroup();
    await wantThreadHistory("conv-1");
    await collect({ receipts: false });
    const { requestId } = (await threadCatchUp.get("conv-1"))!;
    const part = (identity: string, messages: Record<string, unknown>[]) =>
      queued({
        payload: from(
          identity,
          JSON.stringify({ v: 1, kind: "thread-history", requestId, seq: 1, last: true, messages })
        ),
      });

    api.collectQueue.mockResolvedValueOnce({
      items: [
        part("theirs", [
          // No author: the member serving it does not name itself in its own
          // log, and the session it arrives on says who they are.
          { id: "m1", at: "2026-09-01T00:00:00Z", body: "said before you answered", mine: false },
          {
            id: "m2",
            at: "2026-09-01T00:01:00Z",
            body: "put in Sam's mouth",
            mine: false,
            author: 9,
          },
          {
            id: "m3",
            at: "2026-09-01T00:02:00Z",
            body: "edited since",
            mine: true,
            receipt: "read",
            reactions: { "👍": { mine: true, theirs: false } },
            editedAt: "2026-09-01T00:03:00Z",
            rev: 2,
            removedAt: 5,
          },
        ]),
      ],
    });
    await collect({ receipts: false });

    // Theirs, whatever an entry claims; somebody else's words are dropped, and
    // their record of receipts and reactions stays with them.
    const log = await messageLog.get("conv-1");
    expect(log).toEqual([
      {
        id: "m1",
        at: "2026-09-01T00:00:00Z",
        body: "said before you answered",
        mine: false,
        author: 7,
      },
      {
        id: "m3",
        at: "2026-09-01T00:02:00Z",
        body: "edited since",
        mine: false,
        author: 7,
        editedAt: "2026-09-01T00:03:00Z",
        rev: 2,
      },
    ]);
    // One of two has finished, so the ask stays open for the other.
    expect((await threadCatchUp.get("conv-1"))?.waiting).toEqual([9]);

    api.collectQueue.mockResolvedValueOnce({ items: [part("sam", [])] });
    await collect({ receipts: false });
    expect(await threadCatchUp.get("conv-1")).toBeUndefined();
  });

  it("ignores a transfer that answers no ask of its own", async () => {
    asGroup();
    api.collectQueue.mockResolvedValueOnce({
      items: [
        queued({
          payload: from(
            "theirs",
            JSON.stringify({
              v: 1,
              kind: "thread-history",
              requestId: "never-asked",
              seq: 1,
              last: true,
              messages: [
                { id: "m9", at: "2026-09-01T00:00:00Z", body: "unasked for", mine: false },
              ],
            })
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("sends a member who asks only what this account said, from their side of it", async () => {
    asGroup();
    await messageLog.append("conv-1", {
      id: "m1",
      at: "2026-09-01T00:00:00Z",
      body: "mine",
      mine: true,
      receipt: "read",
    });
    await messageLog.append("conv-1", {
      id: "m2",
      at: "2026-09-01T00:01:00Z",
      body: "theirs",
      mine: false,
      author: 7,
    });
    api.collectQueue.mockResolvedValueOnce({
      items: [
        queued({
          payload: from(
            "theirs",
            JSON.stringify({ v: 1, kind: "thread-history-request", requestId: "r1" })
          ),
        }),
      ],
    });

    await collect({ receipts: false });

    const served = sent().filter((row) => row.envelope.kind === "thread-history");
    const carried = served.flatMap(
      (row) => (row.envelope.messages ?? []) as Record<string, unknown>[]
    );
    // Everybody else sends their own. This account's arrives as theirs, with
    // no author -- the far end takes that from the session -- and none of the
    // receipts this account kept about its own copies.
    expect(carried).toEqual([{ id: "m1", at: "2026-09-01T00:00:00Z", body: "mine", mine: false }]);
    // Terminated, so the far end knows it has the lot and stops asking.
    expect(served.at(-1)?.envelope).toMatchObject({ last: true, messages: [] });
  });

  it("says nothing about a transfer, because it is not news", async () => {
    asGroup();
    await wantThreadHistory("conv-1");

    await collect({ receipts: false });

    const askedWith = api.sendMessages.mock.calls.find(([, body]) =>
      body.messages.some(
        (message) => JSON.parse(JSON.parse(message.payload).body).kind === "thread-history-request"
      )
    );
    expect(askedWith?.[1]).toMatchObject({ silent: true });
  });
});

describe("sending", () => {
  it("sends to another person's changed devices, and notes the change for the thread", async () => {
    await sendText("conv-1", [7], "establishes the directory baseline");
    api.sendMessages.mockClear();
    const REPLACEMENT = {
      device_id: "replacement",
      identity_key: "new-key",
      fingerprint_key: "fp",
      signature: "signed:7",
    };
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [REPLACEMENT] });
    api.claimSessionKeys.mockResolvedValue({
      user_id: 7,
      devices: [{ ...REPLACEMENT, one_time_key: ONE_TIME_KEY }],
    });

    await sendText("conv-1", [7], "after they reinstalled");

    const [, body] = api.sendMessages.mock.calls.at(-1)!;
    expect(body.messages.map((m) => m.recipient_device_id)).toContain("replacement");
    expect(await peerKeyChanges.all()).toEqual([]);
    expect(Object.keys(await peerDeviceChanges.all())).toEqual(["7"]);
  });

  it("still reports a genuine absence of devices as one", async () => {
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [] });

    await expect(sendText("conv-1", [7], "hello")).rejects.toBeInstanceOf(
      RecipientHasNoDeviceError
    );
  });

  it("takes a device only on a signature that holds, and its one-time key only signed", async () => {
    const SIGNED = { ...THEIRS, signature: "signed:7" };
    // Listed on this account, but signed as somebody else's.
    const ELSEWHERE = {
      device_id: "device-x",
      identity_key: "x",
      fingerprint_key: "fp",
      signature: "signed:8",
    };
    const UNSIGNED_KEY = {
      device_id: "device-u",
      identity_key: "u",
      fingerprint_key: "fp",
      signature: "signed:7",
    };
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [SIGNED, ELSEWHERE, UNSIGNED_KEY] });
    api.claimSessionKeys.mockResolvedValue({
      user_id: 7,
      devices: [
        { ...SIGNED, one_time_key: { ...ONE_TIME_KEY, fallback: true } },
        { ...UNSIGNED_KEY, one_time_key: { key_id: "k", public_key: "pk" } },
      ],
    });

    await sendText("conv-1", [7], "to the signed device");

    // The one that does not verify is not claimed from, and not held either:
    // there is nothing about it for anybody to confirm.
    expect(api.claimSessionKeys).toHaveBeenCalledWith(7, {
      device_ids: [THEIRS.device_id, "device-u"],
    });
    expect(await peerKeyChanges.all()).toEqual([]);
    expect(openOutbound).toHaveBeenCalledWith("account", "theirs", "fp", "pk", "otk-signed", true);
    const [, body] = api.sendMessages.mock.calls.at(-1)!;
    expect(body.messages.map((m) => m.recipient_device_id)).toEqual([
      THEIRS.device_id,
      OUR_PHONE.id,
    ]);
  });

  it("spends a prekey opening a conversation and none keeping it going", async () => {
    // Claiming deletes a single-use key from the recipient's pool. Doing it per
    // message drains the pool of a busy conversation for nothing: the session
    // it opened is still there.
    await sendText("conv-1", [7], "first");
    await sendText("conv-1", [7], "second");
    // A message somebody typed is news, and says so.
    expect(api.sendMessages.mock.calls[0][1].silent).toBe(false);

    // Claimed only for the device with no session yet.
    expect(api.claimSessionKeys).toHaveBeenCalledTimes(1);
    expect(api.claimSessionKeys).toHaveBeenCalledWith(7, { device_ids: [THEIRS.device_id] });
    expect(api.sendMessages).toHaveBeenCalledTimes(2);
  });

  it("addresses this account's other devices as well as theirs", async () => {
    await sendText("conv-1", [7], "hello");

    const [, body] = api.sendMessages.mock.calls[0];
    expect(
      body.messages.map((message: { recipient_device_id: string }) => message.recipient_device_id)
    ).toEqual([THEIRS.device_id, OUR_PHONE.id]);
  });

  it("advances the session once per message when two are sent at once", async () => {
    // Two tabs on the same conversation. A ratchet step read and written
    // without care loses one of them, and the message that claimed the same
    // place in the conversation is one the far end cannot open.
    await sendText("conv-1", [7], "opens the session");

    await Promise.all([sendText("conv-1", [7], "two"), sendText("conv-1", [7], "three")]);

    expect(await sessionPickle.get(`session:${THEIRS.identity_key}`)).toBe("session:theirs!!!");
  });

  it("refuses when none of their devices can be opened either", async () => {
    // A device that published nothing claimable is one this message cannot
    // reach, and if that is all of them the message reaches nobody at all.
    api.claimSessionKeys.mockResolvedValue({
      user_id: 7,
      devices: [{ ...THEIRS, one_time_key: null }],
    });

    await expect(sendText("conv-1", [7], "hello")).rejects.toBeInstanceOf(
      RecipientHasNoDeviceError
    );
    expect(api.sendMessages).not.toHaveBeenCalled();
    expect(await messageLog.get("conv-1")).toEqual([]);
  });

  it("refuses to write a message into a thread nobody can receive", async () => {
    api.readDirectory.mockResolvedValue({ user_id: 7, devices: [] });

    await expect(sendText("conv-1", [7], "hello")).rejects.toBeInstanceOf(
      RecipientHasNoDeviceError
    );
    expect(api.sendMessages).not.toHaveBeenCalled();
    expect(await messageLog.get("conv-1")).toEqual([]);
  });
});

describe("registering", () => {
  it("withdraws a device it registered after its turn was taken over", async () => {
    // A registration slower than the window the next tab waits out. Both are
    // registered, but only one set of private keys survives — so the device
    // whose keys were dropped is taken back off the server rather than left
    // collecting messages nothing can open.
    await forgetDevice();
    api.registerDevice.mockImplementation(async () => {
      // What the tab that took over did while this registration was in flight.
      const base = Date.now();
      const clock = vi.spyOn(Date, "now").mockReturnValue(base + 31_000);
      const turn = await deviceClaim.take();
      clock.mockRestore();
      await deviceClaim.settle(turn as string, "device-quick", "pickle-quick");
      return {
        devices: [ownDevice({ id: "device-slow", identity_key: "slow" })],
        device_id: "device-slow",
      };
    });
    api.removeDevice.mockResolvedValue(undefined);

    await expect(ensureDevice()).resolves.toBe("device-quick");
    expect(api.removeDevice).toHaveBeenCalledWith("device-slow");
    expect(await accountPickle.get()).toBe("pickle-quick");
  });

  it("registers signed, and lets a device registered into an empty browser ask for the history", async () => {
    await forgetDevice();
    api.registerDevice.mockResolvedValue({
      devices: [ownDevice({ id: "device-fresh", identity_key: "fresh" }), ownDevice(OUR_PHONE)],
      device_id: "device-fresh",
    });

    // The device the server says it created, wherever the list puts it.
    await expect(ensureDevice()).resolves.toBe("device-fresh");
    // Signed as this account's, with every key it publishes signed too.
    expect(api.registerDevice).toHaveBeenCalledWith(
      expect.objectContaining({
        signature: "signed:1",
        fallback_key: expect.objectContaining({ signature: "fallback-signed" }),
        one_time_keys: expect.arrayContaining([
          expect.objectContaining({ signature: "otk-signed0" }),
        ]),
      })
    );
    expect(await historyAsk.get()).toBe("eligible");
  });

  it("settles the question against the browser it registers into", async () => {
    // A device revoked and registered again in a browser that kept its
    // threads. It is a new device id with an old history, and it has nothing
    // to ask anybody for.
    await forgetDevice();
    await messageLog.append("conv-1", {
      id: "m1",
      at: "2026-09-01T00:00:00Z",
      body: "still here",
      mine: false,
    });
    api.registerDevice.mockResolvedValue({
      devices: [ownDevice(OUR_PHONE), ownDevice({ id: "device-fresh", identity_key: "fresh" })],
      device_id: "device-fresh",
    });

    await ensureDevice();

    expect(await historyAsk.get()).toBe("closed");
  });
});

describe("signing out", () => {
  it("takes the device off the server and the messages off this browser", async () => {
    api.removeDevice.mockResolvedValue(undefined);
    api.collectQueue.mockResolvedValue({
      items: [queued({ payload: from("theirs", "read on this device") })],
    });
    await collect();
    expect(await messageLog.get("conv-1")).toHaveLength(1);

    await forgetMessagesOnThisDevice();

    expect(api.removeDevice).toHaveBeenCalledWith(OURS.id);
    expect(await messageLog.get("conv-1")).toEqual([]);
    expect(await deviceId.get()).toBeUndefined();
    expect(await accountPickle.get()).toBeUndefined();
    // The worker holds the pickle key it unwrapped, so it goes with the store.
    expect(stopRatchet).toHaveBeenCalled();
  });
});

describe("the prekey pool", () => {
  it("is topped back up when it runs low", async () => {
    // Nothing else refills it: the server has never held a private half.
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS, 3)] });

    await collect();

    expect(api.topUpKeys).toHaveBeenCalledWith(
      expect.objectContaining({ device_id: OURS.id, one_time_keys: expect.any(Array) })
    );
    expect(api.topUpKeys.mock.calls[0][0].one_time_keys).toHaveLength(47);
  });

  it("is left alone while it is still deep", async () => {
    await collect();

    expect(api.topUpKeys).not.toHaveBeenCalled();
  });

  it("publishes nothing it did not keep the private half of", async () => {
    // The account is written first and the keys published second. A failed
    // write must not leave a key on the server that this device cannot answer.
    await accountPickle.set("account");
    api.listDevices.mockResolvedValue({ devices: [ownDevice(OURS, 0)] });
    api.topUpKeys.mockRejectedValue(new Error("network"));

    await collect();

    expect(await accountPickle.get()).toBe("account+50");
  });
});

/**
 * What counts as unread, on a device that keeps the only copy of the thread.
 *
 * The two sides stamp their messages from two clocks — theirs by the server,
 * mine by this browser — so the marker has to be taken from one of them or the
 * count is a guess about which clock is right.
 */
describe("unread", () => {
  const CONVERSATION = "conv-1";

  it("counts what arrived after the thread was last looked at", async () => {
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "first",
      at: "2026-09-01T10:00:00Z",
      mine: false,
    });
    await markRead(CONVERSATION);
    await messageLog.append(CONVERSATION, {
      id: "m2",
      body: "second",
      at: "2026-09-01T11:00:00Z",
      mine: false,
    });

    expect(await unreadIn(CONVERSATION)).toBe(1);
  });

  it("does not count your own", async () => {
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "mine",
      at: "2026-09-01T10:00:00Z",
      mine: true,
    });

    expect(await unreadIn(CONVERSATION)).toBe(0);
  });

  it("counts two that landed in the same millisecond", async () => {
    // A burst arrives with one timestamp on all of it. Counted by time, the
    // second one would already be behind the marker the first one set.
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "first",
      at: "2026-09-01T10:00:00Z",
      mine: false,
    });
    await markRead(CONVERSATION);
    await messageLog.append(CONVERSATION, {
      id: "m2",
      body: "second, same instant",
      at: "2026-09-01T10:00:00Z",
      mine: false,
    });

    expect(await unreadIn(CONVERSATION)).toBe(1);
  });

  it("survives a browser clock running ahead of the server", async () => {
    // The message this device wrote is stamped from a clock hours ahead. A
    // marker taken from it would swallow everything that arrives next.
    await messageLog.append(CONVERSATION, {
      id: "m1",
      body: "sent from a fast clock",
      at: "2099-01-01T00:00:00Z",
      mine: true,
    });
    await markRead(CONVERSATION);
    await messageLog.append(CONVERSATION, {
      id: "m2",
      body: "their reply, stamped by the server",
      at: "2026-09-01T11:00:00Z",
      mine: false,
    });

    expect(await unreadIn(CONVERSATION)).toBe(1);
  });
});
